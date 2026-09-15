"""Gravacao da camada bronze: resposta crua da API, comprimida, particionada.

Layout:
    <dir_bronze>/dt=2026-08-26/hh=14/20260826T143000Z.pb.gz

Decisoes:

- Gravar cru, sem decodificar. Se o parsing da camada seguinte tiver bug, o
  bruto permite reprocessar. A camada bronze nunca e perdida nem reescrita.
- Particionar por dt e hh desde o primeiro arquivo. Reparticionar depois, com
  milhoes de arquivos, e caro. E dt/hh em UTC: horario local tem mudanca de
  fuso historica e ambiguidade; conversao para horario de BH e trabalho da
  camada silver.
- Um arquivo por coleta gera 2.880 arquivos por dia, o classico problema de
  small files que mata leitura em Spark. Isso e aceito aqui de proposito:
  gravar pequeno e seguro (uma coleta com problema afeta so o proprio
  arquivo), ler pequeno e lento. A compactacao horaria da fase 1 junta a hora
  fechada num unico Parquet. Cada responsabilidade num processo.
"""

from __future__ import annotations

import gzip
import os
from datetime import datetime, timezone
from pathlib import Path


def caminho_arquivo(dir_bronze: Path, instante: datetime) -> Path:
    utc = instante.astimezone(timezone.utc)
    return (
        dir_bronze
        / f"dt={utc:%Y-%m-%d}"
        / f"hh={utc:%H}"
        / f"{utc:%Y%m%dT%H%M%S}Z.pb.gz"
    )


def gravar_atomico(destino: Path, conteudo: bytes) -> int:
    """Grava `conteudo` comprimido em `destino` e devolve os bytes gravados.

    Escreve num temporario e renomeia. O rename e atomico no mesmo sistema de
    arquivos, entao quem le a particao (a compactacao) nunca ve arquivo pela
    metade, mesmo se a VM cair no meio da escrita. O temporario comeca com "."
    para que Spark e a compactacao o ignorem se sobrar de um crash.

    Nunca sobrescreve: bronze e imutavel. Arquivo existente vira erro.
    """
    if destino.exists():
        raise FileExistsError(f"arquivo bronze ja existe: {destino}")
    destino.parent.mkdir(parents=True, exist_ok=True)

    # mtime=0 deixa o gzip deterministico: a mesma resposta gera o mesmo
    # arquivo, byte a byte. Facilita auditar repeticoes por hash.
    comprimido = gzip.compress(conteudo, compresslevel=6, mtime=0)

    temporario = destino.with_name(f".{destino.name}.tmp")
    with open(temporario, "wb") as f:
        f.write(comprimido)
        f.flush()
        # fsync antes do rename: sem ele, uma queda de energia pode deixar o
        # nome novo apontando para bloco ainda nao escrito no disco.
        os.fsync(f.fileno())
    os.replace(temporario, destino)
    return len(comprimido)


def mtime_mais_recente(dir_bronze: Path, agora: datetime) -> float | None:
    """mtime do arquivo mais novo nas particoes da hora atual e da anterior.

    Olha so duas particoes em vez de varrer o lake inteiro, que em poucos meses
    tera centenas de milhares de arquivos. Duas horas bastam porque o limite de
    alerta (10 min) e bem menor que uma hora.
    """
    utc = agora.astimezone(timezone.utc)
    instantes = [utc, datetime.fromtimestamp(utc.timestamp() - 3600, timezone.utc)]
    mais_recente: float | None = None
    for instante in instantes:
        particao = caminho_arquivo(dir_bronze, instante).parent
        if not particao.is_dir():
            continue
        for arquivo in particao.glob("*.pb.gz"):
            m = arquivo.stat().st_mtime
            if mais_recente is None or m > mais_recente:
                mais_recente = m
    return mais_recente
