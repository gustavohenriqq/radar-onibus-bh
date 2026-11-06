"""Regras de calendario das DAGs, sem importar o Airflow.

Ficam separadas para o pytest do projeto testar sem instalar o Airflow, e porque
erro de fuso aqui grava a Gold no dia errado sem nenhuma mensagem.

O Bronze e particionado em hora UTC; a Gold, em dia de BH. A DAG horaria recebe o
inicio do intervalo (hora UTC) e daqui sai todo o resto.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BH = ZoneInfo("America/Sao_Paulo")
DATA_MINIMA = date(2026, 9, 15)


def hora_texto(inicio: datetime) -> str:
    """Inicio do intervalo -> '2026-11-05T14', o formato do --hora da Silver."""
    return inicio.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def data_bh(inicio: datetime) -> date:
    return inicio.astimezone(BH).date()


def nome_manifesto(inicio: datetime) -> str:
    """Nome do manifesto da hora no bucket. O backup envia o conteiner antes do
    manifesto: manifesto presente quer dizer hora inteira no bucket."""
    u = inicio.astimezone(timezone.utc)
    return f"bronze_horario/vehicle_positions/dt={u:%Y-%m-%d}/vp_{u:%Y%m%dT%H}.pb.json"


def vars_gold(de: date, ate: date) -> str:
    return "{data_inicio: %s, data_fim: %s}" % (max(de, DATA_MINIMA), ate)


def janela_gold_da_hora(inicio: datetime) -> str:
    """Uma hora nova muda o dia dela e, se for de madrugada, o dia anterior: uma
    viagem que cruzou a meia-noite so termina de ser vista agora. Por isso a Gold
    refaz ontem e hoje a cada hora."""
    d = data_bh(inicio)
    return vars_gold(d - timedelta(days=1), d)


def janela_gold_do_reprocessamento(de: str, ate: str) -> str:
    """Silver de `de` a `ate` mudou: a Gold refaz tambem o dia seguinte, cujas
    viagens da madrugada comecaram em `ate`."""
    d0, d1 = date.fromisoformat(de), date.fromisoformat(ate)
    if d1 < d0:
        raise ValueError(f"ate {ate} antes de de {de}")
    return vars_gold(d0, d1 + timedelta(days=1))


def fecha_dia_bh(inicio: datetime) -> bool:
    """A hora UTC que comeca em `inicio` e a ultima do dia de BH?"""
    return (inicio + timedelta(hours=1)).astimezone(BH).hour == 0


def fecha_semana_bh(inicio: datetime) -> bool:
    """Ultima hora do domingo em BH: a manutencao semanal roda uma vez."""
    return fecha_dia_bh(inicio) and data_bh(inicio).weekday() == 6
