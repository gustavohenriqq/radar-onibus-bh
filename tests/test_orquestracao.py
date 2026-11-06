"""Regras de calendario das DAGs: fuso, janela da Gold e nome no bucket.

O Airflow nao entra aqui: as regras moram em orquestracao/dags/radar_comum.py,
sem dependencia dele. As DAGs sao conferidas no proprio Airflow, na VM.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from compactacao.horas import Hora
from orquestracao.dags.radar_comum import (
    data_bh,
    fecha_dia_bh,
    fecha_semana_bh,
    hora_texto,
    janela_gold_da_hora,
    janela_gold_do_reprocessamento,
    nome_manifesto,
)

UTC = timezone.utc


def test_hora_utc_vira_o_formato_da_silver():
    assert hora_texto(datetime(2026, 11, 5, 14, tzinfo=UTC)) == "2026-11-05T14"


def test_manifesto_tem_o_mesmo_nome_que_o_backup_grava():
    """O sensor monta o nome sozinho; se o layout do Bronze mudar, quebra aqui."""
    raiz = Path("dados")
    for dt, hh in [("2026-11-05", "14"), ("2026-12-31", "23"), ("2027-01-01", "00")]:
        inicio = datetime.strptime(f"{dt}T{hh}", "%Y-%m-%dT%H").replace(tzinfo=UTC)
        esperado = Hora(dt, hh).manifesto(raiz / "bronze_horario" / "vehicle_positions")
        assert nome_manifesto(inicio) == esperado.relative_to(raiz).as_posix()


def test_madrugada_utc_ainda_e_o_dia_anterior_em_bh():
    # 02:00 UTC de 06/11 = 23:00 de 05/11 em BH
    assert data_bh(datetime(2026, 11, 6, 2, tzinfo=UTC)).isoformat() == "2026-11-05"
    assert janela_gold_da_hora(datetime(2026, 11, 6, 2, tzinfo=UTC)) == \
        "{data_inicio: 2026-11-04, data_fim: 2026-11-05}"
    assert janela_gold_da_hora(datetime(2026, 11, 6, 3, tzinfo=UTC)) == \
        "{data_inicio: 2026-11-05, data_fim: 2026-11-06}"


def test_janela_da_gold_nunca_comeca_antes_do_primeiro_dia_cheio():
    assert janela_gold_da_hora(datetime(2026, 9, 15, 12, tzinfo=UTC)) == \
        "{data_inicio: 2026-09-15, data_fim: 2026-09-15}"


def test_so_a_ultima_hora_utc_do_dia_de_bh_fecha_o_dia():
    inicio = datetime(2026, 11, 5, 3, tzinfo=UTC)  # 00:00 de 05/11 em BH
    fechas = [h for h in range(24) if fecha_dia_bh(inicio + timedelta(hours=h))]
    assert fechas == [23]  # 02:00 UTC de 06/11, 23:00 em BH


def test_manutencao_semanal_so_no_fim_do_domingo():
    # 08/11/2026 e domingo; a ultima hora dele em BH comeca 02:00 UTC de 09/11.
    assert fecha_semana_bh(datetime(2026, 11, 9, 2, tzinfo=UTC))
    assert not fecha_semana_bh(datetime(2026, 11, 8, 2, tzinfo=UTC))  # fim do sabado
    assert not fecha_semana_bh(datetime(2026, 11, 9, 1, tzinfo=UTC))


def test_reprocessar_refaz_tambem_o_dia_seguinte_na_gold():
    assert janela_gold_do_reprocessamento("2026-10-19", "2026-10-25") == \
        "{data_inicio: 2026-10-19, data_fim: 2026-10-26}"
    with pytest.raises(ValueError):
        janela_gold_do_reprocessamento("2026-10-25", "2026-10-19")
