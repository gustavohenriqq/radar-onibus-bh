"""Consultas e conciliacao do painel. Python puro: o banco nao entra aqui."""
from datetime import date

import pytest

from painel.conciliar import comparar
from painel.consultas import METRICAS, filtro, sql_metricas


def test_filtro_passa_valores_por_parametro():
    onde, params = filtro(date(2026, 10, 1), date(2026, 10, 7), "dia_util", True, ["9105"])
    assert "9105" not in onde and "dia_util" not in onde
    assert params == [date(2026, 10, 1), date(2026, 10, 7), "dia_util", True, ["9105"]]
    assert filtro(date(2026, 10, 1), date(2026, 10, 7))[1] == [date(2026, 10, 1), date(2026, 10, 7)]


def test_sql_recusa_chave_fora_da_lista():
    with pytest.raises(ValueError):
        sql_metricas(["route_id; drop table x"], "true")


def test_sql_tem_todas_as_metricas_da_analise():
    sql = sql_metricas(["route_id"], "true")
    for m in METRICAS:
        assert f" as {m}" in sql
    assert sql.endswith("group by route_id order by route_id")


def test_comparar_tolera_meia_casa_e_acusa_o_resto():
    exp = [{"k": "a", "x": "1.234"}, {"k": "b", "x": "2.000"}, {"k": "c", "x": ""}]
    obt = [{"k": "a", "x": 1.2344}, {"k": "b", "x": 2.0006}, {"k": "c", "x": None}, {"k": "d", "x": 1.0}]
    erros = comparar("t", exp, obt, ["k"], [("x", 3)])
    assert erros == ["t ('d',): so no banco", "t ('b',) x: CSV 2.000, banco 2.0006"]


def test_csv_vazio_e_falha():
    assert comparar("t", [], [{"k": "a"}], ["k"], []) == ["t: CSV vazio"]


def test_filtro_paradas_sem_datas_e_por_parametro():
    from painel.consultas import filtro_paradas
    onde, params = filtro_paradas("sabado", False)
    assert "data_bh" not in onde and "sabado" not in onde
    assert params == ["sabado", False]
    assert filtro_paradas() == ("true", [])


def test_sql_paradas_e_hist_usam_as_mesmas_metricas():
    from painel.consultas import sql_hist, sql_paradas
    sql = sql_paradas("true")
    for m in METRICAS:
        assert f" as {m}" in sql
    assert "from radar.paradas_28d" in sql and sql.endswith("having sum(soma) / 3600 >= %s")
    assert sql_hist("true").startswith("select classe, sum(headways)")


def test_formato_brasileiro():
    import numpy as np

    from painel.formato import br, data_br, pct
    assert br(1234567.891, 2) == "1.234.567,89"
    assert pct(0.12345) == "12,3%"
    assert br(None) == "sem dado" and pct(float("nan")) == "sem dado" and br(np.float64("nan")) == "sem dado"
    assert data_br(date(2026, 11, 9)) == "09/11/2026"
