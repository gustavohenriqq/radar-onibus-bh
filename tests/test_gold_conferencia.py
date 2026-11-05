"""Testes da segunda conta da Gold. Python puro: rodam sem Spark e sem dbt."""

import pytest

from gold.conferencia import (
    aprender_mapa,
    calcular,
    comparar,
    filtrar_repeticao,
    janelas_feed_parado,
    metricas_da_parada,
    passagens_da_viagem,
)


def ping(unix, seq, parada, viagem="v1", onibus="a", rota="r1", sentido=0, letreiro="l"):
    return {
        "unix": unix, "stop_sequence": seq, "stop_id": parada, "viagem_id": viagem,
        "vehicle_id": onibus, "route_id": rota, "direction_id": sentido, "letreiro": letreiro,
    }


def test_mapa_escolhe_a_parada_mais_vista_e_desempata_pelo_menor_id():
    pings = [ping(1, 5, "b"), ping(2, 5, "b"), ping(3, 5, "a"), ping(4, 6, "z"), ping(5, 6, "y")]
    mapa = aprender_mapa(pings)
    assert mapa[("r1", 0, "l", 5)] == "b"
    assert mapa[("r1", 0, "l", 6)] == "y"


def test_salto_divide_o_intervalo_em_partes_iguais():
    pings = [ping(1000, 5, "p5"), ping(1060, 6, "p6"), ping(1150, 9, "p9")]
    mapa = {("r1", 0, "l", 7): "p7", ("r1", 0, "l", 8): "p8"}
    obtido = [(p["stop_sequence"], p["stop_id"], p["unix"]) for p in passagens_da_viagem(pings, mapa)]
    assert obtido == [(5, "p5", 1030.0), (6, "p6", 1075.0), (7, "p7", 1105.0), (8, "p8", 1135.0)]


def test_recuo_nao_repete_passagem():
    pings = [ping(1000, 5, "p5"), ping(1060, 6, "p6"), ping(1120, 5, "p5"),
             ping(1180, 6, "p6"), ping(1240, 7, "p7")]
    obtido = [(p["stop_sequence"], p["unix"]) for p in
              passagens_da_viagem(pings, {("r1", 0, "l", 6): "p6"})]
    assert obtido == [(5, 1030.0), (6, 1210.0)]


def test_buraco_acima_de_cinco_minutos_nao_gera_passagem():
    assert passagens_da_viagem([ping(1000, 5, "p5"), ping(1301, 6, "p6")], {}) == []
    assert len(passagens_da_viagem([ping(1000, 5, "p5"), ping(1300, 6, "p6")], {})) == 1


def test_parada_fora_do_mapa_fica_de_fora():
    obtido = passagens_da_viagem([ping(1000, 5, "p5"), ping(1060, 7, "p7")], {})
    assert [p["stop_sequence"] for p in obtido] == [5]


def test_repeticao_do_mesmo_onibus_e_removida():
    fila = [{"unix": 0.0, "vehicle_id": "a"}, {"unix": 600.0, "vehicle_id": "b"},
            {"unix": 700.0, "vehicle_id": "b"}, {"unix": 1200.0, "vehicle_id": "c"}]
    assert [p["unix"] for p in filtrar_repeticao(fila)] == [0.0, 600.0, 1200.0]


def test_formulas_com_resposta_conhecida():
    m = metricas_da_parada([600.0, 1800.0])
    assert m["headway_medio_min"] == 20
    assert m["cv_headway"] == pytest.approx(0.5)
    assert m["espera_estimada_min"] == pytest.approx(12.5)
    assert m["espera_regular_min"] == 10
    assert m["espera_excesso_min"] == pytest.approx(2.5)


def test_onibus_igualmente_espacados_nao_tem_excesso():
    m = metricas_da_parada([600.0, 600.0, 600.0])
    assert m["cv_headway"] == 0
    assert m["espera_excesso_min"] == 0


def test_calcular_de_ponta_a_ponta_atribui_data_e_faixa_de_bh():
    # Passagens de 02:00 a 02:30 UTC de 21/10, que sao 23:00 a 23:30 de 20/10 em BH.
    # Quatro onibus, um a cada 10 min, dao 3 headways iguais na parada p5.
    base = 1792549770 - 1800
    pings = []
    for i, onibus in enumerate("abcd"):
        inicio = base + i * 600
        pings += [ping(inicio, 5, "p5", viagem=f"v{i}", onibus=onibus),
                  ping(inicio + 60, 6, "p6", viagem=f"v{i}", onibus=onibus)]
    r = calcular(pings, "2026-10-20", "2026-10-21")
    chave = ("r1", 0, "2026-10-20", "noite")
    assert r[chave]["paradas"] == 1
    assert r[chave]["headways"] == 3
    assert r[chave]["headway_medio_min"] == pytest.approx(10)
    assert r[chave]["espera_excesso_min"] == pytest.approx(0)


def test_parada_com_media_zero_fica_fora_da_linha():
    # Quatro onibus informam a passagem no mesmo instante: 3 headways de zero.
    base = 1792549770 - 1800
    pings = []
    for i, onibus in enumerate("abcd"):
        pings += [ping(base, 5, "p5", viagem=f"v{i}", onibus=onibus),
                  ping(base + 60, 6, "p6", viagem=f"v{i}", onibus=onibus)]
    assert calcular(pings, "2026-10-20", "2026-10-21") == {}


def test_feed_parado_e_o_vazio_de_pelo_menos_cinco_minutos_na_frota():
    assert janelas_feed_parado([0, 299, 299, 900, 1199]) == [(299, 900)]


def test_headway_que_atravessa_feed_parado_fica_de_fora():
    # Cinco onibus a cada 10 min dao 4 headways. O feed cai entre o 2o e o 3o.
    base = 1792549770 - 1800
    pings = []
    for i, onibus in enumerate("abcde"):
        inicio = base + i * 600
        pings += [ping(inicio, 5, "p5", viagem=f"v{i}", onibus=onibus),
                  ping(inicio + 60, 6, "p6", viagem=f"v{i}", onibus=onibus)]
    args = ("2026-10-20", "2026-10-21")
    chave = ("r1", 0, "2026-10-20", "noite")
    assert calcular(pings, *args)[chave]["headways"] == 4
    janela = [(base + 700, base + 1100)]
    assert calcular(pings, *args, janelas=janela)[chave]["headways"] == 3


def test_comparar_acusa_valor_diferente_e_chave_que_falta():
    a = {("x",): {"cv_headway": 0.5}, ("y",): {"cv_headway": 0.1}}
    b = {("x",): {"cv_headway": 0.6}, ("z",): {"cv_headway": 0.1}}
    erros = comparar(a, b)
    assert len(erros) == 3
    assert comparar(a, a) == []
