"""Manutencao da tabela Delta da Silver, separada do MERGE horario.

Uso:
    python -m silver.manutencao optimize --de 2026-11-04 --ate 2026-11-04
    python -m silver.manutencao vacuum

Por que separada: com MERGE de hora em hora, rodar OPTIMIZE a cada hora
reescreveria o dia inteiro 24 vezes, e cada reescrita fica no disco ate o VACUUM.
O Airflow roda o OPTIMIZE uma vez, quando o dia de BH fecha, e o VACUUM uma vez
por semana.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from silver.janela import dias
from silver.processar import limpar_versoes, otimizar, sessao


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="OPTIMIZE e VACUUM da Silver")
    p.add_argument("acao", choices=["optimize", "vacuum"])
    p.add_argument("--de", type=date.fromisoformat)
    p.add_argument("--ate", type=date.fromisoformat)
    p.add_argument("--destino", default=os.environ.get("SILVER_DESTINO", "dados/silver/posicoes"))
    p.add_argument("--reter-horas", type=int, default=168)
    args = p.parse_args(argv)
    if args.acao == "optimize" and not (args.de and args.ate):
        p.error("optimize pede --de e --ate")

    destino = str(Path(args.destino).resolve())
    t0 = time.perf_counter()
    spark = sessao()
    spark.sparkContext.setLogLevel("WARN")
    if args.acao == "optimize":
        datas = [str(d) for d in dias(args.de, args.ate)]
        otimizar(spark, destino, datas)
        saida = {"acao": "optimize", "datas": datas}
    else:
        limpar_versoes(spark, destino, args.reter_horas)
        saida = {"acao": "vacuum", "reter_horas": args.reter_horas}
    spark.stop()
    print(json.dumps({**saida, "segundos": round(time.perf_counter() - t0, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
