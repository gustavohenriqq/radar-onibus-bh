"""Traz do bucket de backup os contêineres de uma janela de datas em BH.

Uso: python -m silver.sincronizar --de 2026-09-15 --ate 2026-09-21 [--dados DIR]

A Silver roda fora da VM (1 GB de RAM nao comporta Spark), e a fonte dela e o
proprio backup: o mesmo bucket que protege o historico serve de entrada para o
processamento, sem abrir acesso de leitura ao disco da VM.

So baixa o que falta, e so aceita o que bate o SHA-256 do manifesto.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from backup.remoto import NaoEncontrado, Remoto
from compactacao import formato
from compactacao.horas import Hora
from silver.janela import dias, horas_utc_do_dia


def local_valido(hora: Hora, dir_horario: Path) -> bool:
    c, m = hora.conteiner(dir_horario), hora.manifesto(dir_horario)
    if not (c.exists() and m.exists()):
        return False
    return formato.sha256_arquivo(c) == json.loads(m.read_text(encoding="utf-8"))["sha256_conteiner"]


def sincronizar_hora(hora: Hora, remoto: Remoto, dados: Path) -> str:
    dir_horario = dados / "bronze_horario" / "vehicle_positions"
    if local_valido(hora, dir_horario):
        return "ja_tinha"
    for caminho in (hora.manifesto(dir_horario), hora.conteiner(dir_horario)):
        remoto.baixar(caminho.relative_to(dados).as_posix(), caminho)
    if not local_valido(hora, dir_horario):
        raise RuntimeError(f"{hora.dt} {hora.hh}h: sha256 do conteiner baixado difere do manifesto")
    return "baixada"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Baixa do backup os contêineres de uma janela em BH")
    p.add_argument("--de", required=True, type=date.fromisoformat)
    p.add_argument("--ate", required=True, type=date.fromisoformat)
    p.add_argument("--dados", type=Path, default=Path(os.environ.get("SILVER_BRONZE_DIR", "dados")))
    args = p.parse_args(argv)

    load_dotenv(override=False)
    url = os.environ.get("BACKUP_PAR_URL", "").strip()
    if not url:
        print("BACKUP_PAR_URL nao definida", file=sys.stderr)
        return 2
    remoto = Remoto(url)

    contagem = {"baixada": 0, "ja_tinha": 0, "ausente": 0}
    falhas = 0
    for dia in dias(args.de, args.ate):
        for hora in horas_utc_do_dia(dia):
            try:
                contagem[sincronizar_hora(hora, remoto, args.dados)] += 1
            except NaoEncontrado:
                contagem["ausente"] += 1
            except Exception as e:
                falhas += 1
                print(f"FALHA {e}", file=sys.stderr)
    print(json.dumps({**contagem, "falhas": falhas}))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
