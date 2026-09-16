"""Job horario: consolida cada hora fechada do Bronze num unico conteiner.

Uso: python -m compactacao.compactar [--folga-min N] [--limite N]

Por que existe: a 30 s por coleta sao 2.880 arquivos por dia e cerca de 87,7
mil por mes. Esse e o problema classico de small files, que trava leitura em
Spark e incha a lista de arquivos. Gravar pequeno e seguro, ler pequeno e
lento, entao cada responsabilidade fica num processo.

O que este job NAO faz, de proposito:
- nao deduplica. Bronze guarda o que a API devolveu, inclusive a repeticao, que
  e informacao sobre a fonte. A dedup por (vehicle_id, timestamp) fica na Silver.
- nao decodifica. Campo novo que a operadora venha a enviar continua guardado.
- nao apaga nada. Apagar original e outro job, com quarentena.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone

import requests

from coletor import registro
from coletor.config import Config
from compactacao import formato
from compactacao.horas import Hora, pendentes

log = logging.getLogger("coletor")


def compactar_hora(hora: Hora, cfg: Config) -> dict:
    origens = sorted(hora.dir_origem(cfg.dir_bronze).glob("*.pb.gz"))
    if not origens:
        raise RuntimeError(f"hora sem arquivos: {hora}")
    t0 = time.perf_counter()
    r = formato.escrever(hora.conteiner(cfg.dir_bronze_horario), origens, cfg.compactacao_nivel_zstd)

    bytes_originais = sum(p.stat().st_size for p in origens)
    manifesto = {
        "versao_formato": 1,
        "dt": hora.dt,
        "hh": hora.hh,
        "coletas": r.coletas,
        "primeira_coleta": origens[0].name[:16],
        "ultima_coleta": origens[-1].name[:16],
        "bytes_originais": bytes_originais,
        "bytes_protobuf": r.bytes_protobuf,
        "bytes_conteiner": r.bytes_conteiner,
        "sha256_conteiner": r.sha256_conteiner,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Hash de cada original: e o que permite provar, na hora de apagar, que
        # o conteiner reproduz exatamente o que foi coletado.
        "sha256_originais": r.sha256_originais,
    }
    caminho = hora.manifesto(cfg.dir_bronze_horario)
    temporario = caminho.with_name(f".{caminho.name}.tmp")
    temporario.write_text(json.dumps(manifesto, indent=1), encoding="utf-8")
    temporario.replace(caminho)

    # Conferencia imediata: le de volta o que acabou de escrever e compara o
    # hash de cada coleta reconstruida com o do arquivo original. Sem isso, o
    # job diria "compactei" sobre um arquivo que ninguem verificou.
    conferidas = 0
    for nome, protobuf in formato.ler(hora.conteiner(cfg.dir_bronze_horario)):
        esperado = r.sha256_originais[f"{nome}.pb.gz"]
        if hashlib.sha256(formato.reconstruir_gz(protobuf)).hexdigest() != esperado:
            raise RuntimeError(f"conferencia falhou em {nome}")
        conferidas += 1
    if conferidas != r.coletas:
        raise RuntimeError(f"conteiner tem {conferidas} coletas e deveria ter {r.coletas}")

    return {
        "hora": f"{hora.dt} {hora.hh}h",
        "coletas": r.coletas,
        "mb_originais": round(bytes_originais / 1048576, 2),
        "mb_conteiner": round(r.bytes_conteiner / 1048576, 2),
        "reducao_pct": round(100 * (1 - r.bytes_conteiner / max(bytes_originais, 1)), 1),
        "segundos": round(time.perf_counter() - t0, 1),
    }


def ping(url: str | None, sufixo: str = "") -> None:
    if not url:
        return
    try:
        requests.get(url + sufixo, timeout=10)
    except requests.RequestException as e:
        log.warning("healthcheck_falhou", extra={"campos": {"erro": type(e).__name__}})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compacta horas fechadas do Bronze")
    p.add_argument("--folga-min", type=int, default=None, help="minutos de espera depois de a hora fechar")
    p.add_argument("--limite", type=int, default=None, help="maximo de horas nesta execucao")
    args = p.parse_args(argv)

    cfg = Config.do_ambiente(exigir_url=False)
    registro.configurar(cfg.dir_log, "compactacao.jsonl")
    folga = cfg.compactacao_folga_min if args.folga_min is None else args.folga_min
    agora = datetime.now(timezone.utc)

    fila = pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, agora, folga)
    if args.limite:
        fila = fila[: args.limite]
    log.info("inicio", extra={"campos": {"horas_pendentes": len(fila), "folga_min": folga}})

    falhas = 0
    for hora in fila:
        try:
            log.info("compactada", extra={"campos": compactar_hora(hora, cfg)})
        except Exception as e:
            falhas += 1
            log.exception("falha", extra={"campos": {"hora": f"{hora.dt} {hora.hh}", "erro": str(e)[:200]}})

    log.info("fim", extra={"campos": {"compactadas": len(fila) - falhas, "falhas": falhas}})
    # Ping so quando tudo deu certo: job que falha e continua pingando e
    # monitoramento que mente.
    ping(cfg.healthcheck_compactacao_url, "" if falhas == 0 else "/fail")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
