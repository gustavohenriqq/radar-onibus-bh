"""Formato do conteiner horario do Bronze.

Por que um formato proprio em vez de Parquet: o Bronze guarda protobuf cru e
imutavel. Decodificar para colunas aqui seria decidir hoje, com poucos dias de
dado, qual campo importa, e descartaria em silencio qualquer campo novo que a
operadora passe a enviar. Medido em 16/09/2026, numa hora de pico: este
conteiner ocupa 2,16 MB contra 8,94 MB dos arquivos soltos e 4,84 MB do Parquet
com coluna binaria.

Layout, deliberadamente simples para continuar legivel daqui a anos:

    stream zstd
      b"VPBH1\n"                       cabecalho, identifica formato e versao
      repetido, um por coleta:
        16 bytes ASCII                 nome da coleta, ex: 20260915T100000Z
        4 bytes big-endian             tamanho do protobuf em bytes
        N bytes                        protobuf cru, exatamente como a API devolveu

O arquivo original `.pb.gz` e reconstruivel byte a byte a partir daqui, porque o
coletor comprime com gzip nivel 6 e `mtime=0`, que e deterministico. Isso foi
verificado em 60 arquivos espalhados por um dia inteiro: 60 de 60 com SHA-256
identico. E o que autoriza apagar os originais depois.
"""

from __future__ import annotations

import gzip
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import zstandard as zstd

MAGIC = b"VPBH1\n"
TAM_NOME = 16  # 20260915T100000Z
NIVEL_PADRAO = 10


def reconstruir_gz(protobuf: bytes) -> bytes:
    """Recria o .pb.gz original a partir do protobuf cru."""
    return gzip.compress(protobuf, compresslevel=6, mtime=0)


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


@dataclass
class ResultadoEscrita:
    coletas: int
    bytes_protobuf: int
    bytes_conteiner: int
    sha256_conteiner: str
    sha256_originais: dict[str, str]


def escrever(destino: Path, origens: list[Path], nivel: int = NIVEL_PADRAO) -> ResultadoEscrita:
    """Escreve o conteiner de uma hora. Escrita atomica, como no coletor.

    Le um arquivo por vez: a memoria nao cresce com o tamanho da hora, o que
    importa numa VM de 1 GB.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(f".{destino.name}.tmp")
    origens = sorted(origens)
    hashes: dict[str, str] = {}
    total_pb = 0
    with open(temporario, "wb") as saida:
        # closefd=False: sem isso o zstandard fecha o arquivo ao encerrar o
        # fluxo, e o fsync abaixo falharia em arquivo ja fechado.
        c = zstd.ZstdCompressor(level=nivel).stream_writer(saida, closefd=False)
        c.write(MAGIC)
        for origem in origens:
            bruto = open(origem, "rb").read()
            protobuf = gzip.decompress(bruto)
            nome = origem.name[:TAM_NOME].encode("ascii")
            if len(nome) != TAM_NOME:
                raise ValueError(f"nome fora do padrao: {origem.name}")
            c.write(nome)
            c.write(len(protobuf).to_bytes(4, "big"))
            c.write(protobuf)
            hashes[origem.name] = hashlib.sha256(bruto).hexdigest()
            total_pb += len(protobuf)
        c.close()
        saida.flush()
        os.fsync(saida.fileno())
    os.replace(temporario, destino)
    return ResultadoEscrita(
        coletas=len(origens),
        bytes_protobuf=total_pb,
        bytes_conteiner=destino.stat().st_size,
        sha256_conteiner=sha256_arquivo(destino),
        sha256_originais=hashes,
    )


def ler(caminho: Path) -> Iterator[tuple[str, bytes]]:
    """Percorre o conteiner devolvendo (nome_da_coleta, protobuf cru).

    Streaming: nunca carrega a hora inteira na memoria.
    """
    with open(caminho, "rb") as f:
        fluxo = zstd.ZstdDecompressor().stream_reader(f)
        cabecalho = fluxo.read(len(MAGIC))
        if cabecalho != MAGIC:
            raise ValueError(f"cabecalho invalido em {caminho}: {cabecalho!r}")
        while True:
            nome = fluxo.read(TAM_NOME)
            if not nome:
                return
            if len(nome) != TAM_NOME:
                raise ValueError(f"conteiner truncado no nome em {caminho}")
            tamanho_bruto = fluxo.read(4)
            if len(tamanho_bruto) != 4:
                raise ValueError(f"conteiner truncado no tamanho em {caminho}")
            tamanho = int.from_bytes(tamanho_bruto, "big")
            protobuf = _ler_exato(fluxo, tamanho)
            if len(protobuf) != tamanho:
                raise ValueError(f"conteiner truncado no conteudo em {caminho}")
            yield nome.decode("ascii"), protobuf


def _ler_exato(fluxo, tamanho: int) -> bytes:
    # stream_reader pode devolver menos que o pedido; sem este laco, um arquivo
    # integro pareceria truncado.
    partes = []
    faltam = tamanho
    while faltam:
        parte = fluxo.read(faltam)
        if not parte:
            break
        partes.append(parte)
        faltam -= len(parte)
    return b"".join(partes)
