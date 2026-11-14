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


def test_sql_somas_recusa_chave_fora_da_lista_e_agrupa_dia_da_semana():
    from painel.consultas import sql_somas
    with pytest.raises(ValueError):
        sql_somas(["stop_name; drop table x"], "true")
    sql = sql_somas(["route_id", "dia_semana"], "true")
    assert "extract(isodow from data_bh)::int as dia_semana" in sql
    assert sql.endswith("group by route_id, extract(isodow from data_bh)::int")


def test_metricas_em_pandas_repetem_as_formulas_do_sql():
    import pandas as pd
    from painel.consultas import SOMAS, agrega, total
    df = pd.DataFrame([dict(zip(SOMAS, v)) | {"k": k} for k, v in [
        ("a", [1, 10, 6000, 4.2e5, 1.8e5, 2, 1, 4e4, 1, 0, 1, 900]),
        ("b", [2, 30, 18000, 1.5e6, 9.0e5, 3, 0, 2e5, 2, 1, 0, 3000])]])
    t = total(df)
    assert t["excesso_min"] == pytest.approx((1.8e5 + 9.0e5) / 2 / 24000 / 60)
    assert t["regular_min"] == pytest.approx((4.2e5 + 1.5e6) / 2 / 24000 / 60)
    assert t["colados_pct"] == pytest.approx(5 / 40)
    assert t["reducao_pct"] == pytest.approx(2.4e5 / 1.08e6)
    assert t["comboio_pct"] == pytest.approx(1 / 5)
    por = agrega(df, ["k"]).set_index("k")
    assert por.loc["a", "volume_min_h"] == pytest.approx(1.8e5 / 2 / 60 / 3600)


def test_trajeto_pelo_nome_igual_ao_power_bi():
    from painel.paginas import trajeto
    assert trajeto("Estação Diamante/Centro") == "Da estação ao centro"
    assert trajeto("Taquaril / HOSPITAIS") == "Do bairro ao centro"
    assert trajeto("Belvedere / Floresta") == "Entre bairros"
    assert trajeto("Estação Barreiro / Tirol") == "Do bairro à estação"
