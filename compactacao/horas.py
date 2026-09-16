"""Quais horas ja estao fechadas e quais ainda faltam compactar.

Separado do job para poder ser testado sem tocar em disco de producao.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from compactacao import formato


@dataclass(frozen=True)
class Hora:
    dt: str   # 2026-09-15
    hh: str   # 10

    @property
    def inicio(self) -> datetime:
        return datetime.strptime(f"{self.dt}T{self.hh}", "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)

    @property
    def fim(self) -> datetime:
        return self.inicio + timedelta(hours=1)

    def dir_origem(self, dir_bronze: Path) -> Path:
        return dir_bronze / f"dt={self.dt}" / f"hh={self.hh}"

    def conteiner(self, dir_horario: Path) -> Path:
        sem_traco = self.dt.replace("-", "")
        return dir_horario / f"dt={self.dt}" / f"vp_{sem_traco}T{self.hh}.pb.zst"

    def manifesto(self, dir_horario: Path) -> Path:
        return self.conteiner(dir_horario).with_suffix(".json")


def horas_com_dado(dir_bronze: Path) -> list[Hora]:
    horas = []
    for particao in sorted(dir_bronze.glob("dt=*/hh=*")):
        if particao.is_dir() and any(particao.glob("*.pb.gz")):
            horas.append(Hora(particao.parent.name[3:], particao.name[3:]))
    return horas


def fechada(hora: Hora, agora: datetime, folga_min: int) -> bool:
    """A hora H so fecha depois de H+1, porque o nome do arquivo e o horario
    real da coleta: uma coleta atrasada por backoff cai na hora em que
    aconteceu. A folga cobre relogio fora de hora e jitter do timer."""
    return agora >= hora.fim + timedelta(minutes=folga_min)


def conteiner_valido(hora: Hora, dir_horario: Path, dir_bronze: Path) -> tuple[bool, str]:
    """Idempotencia: decide se a hora ja esta compactada e confiavel.

    Rodar o job duas vezes sobre a mesma hora nao pode duplicar nem perder, por
    isso a hora ja compactada e pulada. Mas pular sem conferir seria pior que
    reprocessar: um conteiner truncado por disco cheio ficaria para sempre no
    lugar do dado bom.
    """
    conteiner, manifesto = hora.conteiner(dir_horario), hora.manifesto(dir_horario)
    if not conteiner.exists() or not manifesto.exists():
        return False, "ausente"
    try:
        m = json.loads(manifesto.read_text(encoding="utf-8"))
    except ValueError:
        return False, "manifesto ilegivel"
    if m.get("versao_formato") != 1:
        return False, "versao de formato diferente"
    if conteiner.stat().st_size != m.get("bytes_conteiner"):
        return False, "tamanho diferente do manifesto"
    if formato.sha256_arquivo(conteiner) != m.get("sha256_conteiner"):
        return False, "sha256 diferente do manifesto"
    origens = list(hora.dir_origem(dir_bronze).glob("*.pb.gz"))
    if len(origens) > m.get("coletas", 0):
        # Arquivo novo apareceu depois da compactacao (coleta atrasada, relogio
        # corrigido). Recompactar e mais seguro que ignorar.
        return False, f"origem tem {len(origens)} arquivos e o manifesto {m.get('coletas')}"
    return True, "ok"


def pendentes(dir_bronze: Path, dir_horario: Path, agora: datetime, folga_min: int) -> list[Hora]:
    """Backfill por construcao: devolve TODAS as horas fechadas sem conteiner
    valido, nao so a ultima. Se a VM ficar horas fora do ar, a proxima execucao
    recupera tudo sozinha, sem comando manual."""
    faltando = []
    for hora in horas_com_dado(dir_bronze):
        if not fechada(hora, agora, folga_min):
            continue
        ok, _ = conteiner_valido(hora, dir_horario, dir_bronze)
        if not ok:
            faltando.append(hora)
    return faltando
