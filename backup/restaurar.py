"""Restaura um dia inteiro do bucket de backup e prova que o dado esta intacto.

Uso: python -m backup.restaurar --dia 2026-09-15 --destino ./restauro [--originais]

Roda em qualquer maquina com a BACKUP_PAR_URL no ambiente, inclusive fora da
VM, que e exatamente o cenario em que um backup e usado.

Para cada hora do dia:
1. baixa conteiner e manifesto para <destino>, no mesmo layout de /dados;
2. confere o SHA-256 do conteiner contra o manifesto;
3. reconstroi cada coleta e confere contra o SHA-256 do .pb.gz original,
   gravado no manifesto antes de o original ser apagado.

Com --originais, tambem regrava os .pb.gz por coleta em bronze/, como o coletor
os deixou.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from compactacao import formato
from compactacao.horas import Hora
from backup.remoto import NaoEncontrado, Remoto


def restaurar_hora(hora: Hora, remoto: Remoto, destino: Path, originais: bool) -> dict:
    base = destino / "bronze_horario" / "vehicle_positions"
    conteiner, manifesto = hora.conteiner(base), hora.manifesto(base)
    for caminho in (conteiner, manifesto):
        remoto.baixar(caminho.relative_to(destino).as_posix(), caminho)

    m = json.loads(manifesto.read_text(encoding="utf-8"))
    if formato.sha256_arquivo(conteiner) != m["sha256_conteiner"]:
        raise RuntimeError("sha256 do conteiner difere do manifesto")

    conferidas = 0
    for nome, protobuf in formato.ler(conteiner):
        gz = formato.reconstruir_gz(protobuf)
        if hashlib.sha256(gz).hexdigest() != m["sha256_originais"][f"{nome}.pb.gz"]:
            raise RuntimeError(f"coleta {nome} nao reproduz o original")
        if originais:
            alvo = destino / "bronze" / "vehicle_positions" / f"dt={hora.dt}" / f"hh={hora.hh}" / f"{nome}.pb.gz"
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(gz)
        conferidas += 1
    if conferidas != m["coletas"]:
        raise RuntimeError(f"{conferidas} coletas no conteiner, {m['coletas']} no manifesto")
    return {"coletas": conferidas, "mb": round(conteiner.stat().st_size / 1048576, 2)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Restaura e confere um dia do backup")
    p.add_argument("--dia", required=True, help="AAAA-MM-DD, em UTC como as particoes")
    p.add_argument("--destino", required=True, type=Path)
    p.add_argument("--originais", action="store_true", help="regrava tambem os .pb.gz por coleta")
    args = p.parse_args(argv)
    datetime.strptime(args.dia, "%Y-%m-%d")

    load_dotenv(override=False)
    url = os.environ.get("BACKUP_PAR_URL", "").strip()
    if not url:
        print("BACKUP_PAR_URL nao definida", file=sys.stderr)
        return 2
    remoto = Remoto(url)

    total = horas = 0
    ausentes, falhas = [], []
    for hh in range(24):
        hora = Hora(args.dia, f"{hh:02d}")
        try:
            r = restaurar_hora(hora, remoto, args.destino, args.originais)
        except NaoEncontrado:
            ausentes.append(hora.hh)
            continue
        except Exception as e:
            falhas.append(f"{hora.hh}: {e}")
            continue
        horas += 1
        total += r["coletas"]
        print(f"  {args.dia} {hora.hh}h  {r['coletas']:4d} coletas conferidas  {r['mb']:5.2f} MB")

    print(f"\n{args.dia}: {horas} horas restauradas, {total} coletas conferidas byte a byte")
    if ausentes:
        print(f"horas ausentes no bucket: {', '.join(ausentes)}")
    for f in falhas:
        print(f"FALHA {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
