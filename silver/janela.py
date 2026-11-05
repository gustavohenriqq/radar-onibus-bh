"""Janela de reprocessamento: dia em horario de BH -> horas UTC do Bronze.

O Bronze e particionado em UTC (sem ambiguidade de fuso); a Silver, por data
em BH, que e como qualquer pergunta sobre o servico e feita ("o pico de
segunda-feira"). A conversao acontece so aqui, como o BRIEF decidiu.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from compactacao.horas import Hora

BH = ZoneInfo("America/Sao_Paulo")


def dias(de: date, ate: date) -> list[date]:
    if ate < de:
        raise ValueError("data final antes da inicial")
    return [de + timedelta(days=i) for i in range((ate - de).days + 1)]


def horas_utc_do_dia(dia: date) -> list[Hora]:
    """As horas UTC cujas coletas caem no dia `dia` de BH.

    Pelo fuso, e nao por um "-3" fixo: se o horario de verao voltar, o dia
    passa a ter 23 ou 25 horas e esta funcao continua certa.
    """
    inicio = datetime.combine(dia, time(0), BH).astimezone(timezone.utc)
    fim = datetime.combine(dia + timedelta(days=1), time(0), BH).astimezone(timezone.utc)
    horas, h = [], inicio
    while h < fim:
        horas.append(Hora(h.strftime("%Y-%m-%d"), h.strftime("%H")))
        h += timedelta(hours=1)
    return horas
