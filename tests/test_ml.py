"""Testes da Fase 5. Os de Python puro rodam no Windows; os de Spark, no conteiner."""
from datetime import date

import pytest

from ml import custo, divisao
from ml.features import ALVO, PERMITIDAS, PROIBIDAS


def test_nenhuma_coluna_e_permitida_e_proibida_ao_mesmo_tempo():
    assert not set(PERMITIDAS) & set(PROIBIDAS)


def test_alvo_e_identificadores_estao_proibidos():
    for coluna in (ALVO, "alvo_disfarcado", "m_dia", "viagem_id", "vehicle_id", "data_bh"):
        assert coluna in PROIBIDAS
        assert coluna not in PERMITIDAS


def test_divisao_segue_as_datas_combinadas():
    assert divisao.conjunto(date(2026, 9, 28)) is None
    assert divisao.conjunto(date(2026, 9, 29)) == "treino"
    assert divisao.conjunto(date(2026, 10, 19)) == "treino"
    assert divisao.conjunto(date(2026, 10, 20)) == "validacao"
    assert divisao.conjunto(date(2026, 10, 26)) == "validacao"
    assert divisao.conjunto(date(2026, 10, 27)) == "teste"
    assert divisao.conjunto(date(2026, 11, 6)) == "teste"
    assert divisao.conjunto(date(2026, 11, 7)) is None


def test_backtest_nao_encosta_no_teste():
    for inicio, fim in divisao.BLOCOS_BACKTEST:
        assert inicio > divisao.INICIO
        assert fim <= divisao.FIM_VALIDACAO
        assert (fim - inicio).days == 6


def test_equilibrio_da_hipotese_de_custo_e_60_por_cento():
    assert custo.equilibrio() == pytest.approx(0.6)


def test_curva_junta_empates_e_comeca_em_nunca_alertar():
    pontos = custo.curva([0.9, 0.5, 0.5, 0.1], [1, 1, 0, 0])
    assert pontos == [(float("inf"), 0, 0), (0.9, 1, 1), (0.5, 3, 2), (0.1, 4, 2)]


def test_limiar_so_alerta_onde_a_precisao_paga_o_alerta():
    # Ate 0,5 todo alerta acerta (paga 30, evita 50); abaixo so ha erro.
    probs = [0.95, 0.9, 0.5, 0.4, 0.3]
    alvos = [1, 1, 1, 0, 0]
    assert custo.melhor_limiar(probs, alvos) == 0.5
    r = custo.avaliar(probs, alvos, 0.5)
    assert (r["alertas"], r["acertos"]) == (3, 3)
    assert r["custo_modelo"] == pytest.approx(3 * 30 + (3 - 0.5 * 3) * 100)
    assert r["custo_nunca"] == 300
    assert r["custo_sempre"] == pytest.approx(5 * 30 + (3 - 1.5) * 100)


def test_sem_alerta_que_pague_o_limiar_e_nunca_alertar():
    assert custo.melhor_limiar([0.6, 0.5], [0, 0]) == float("inf")


# --- Spark: so as passagens conhecidas no instante da decisao entram ---------

@pytest.fixture(scope="module")
def spark():
    pytest.importorskip("pyspark")
    pytest.importorskip("delta")
    from silver.processar import sessao
    s = sessao(memoria="1g")
    s.sparkContext.setLogLevel("ERROR")
    yield s


def viagens(spark, saida_c, intervalo_c=30):
    """Tres onibus na mesma linha: A na frente, B no meio, C atras.

    B passa na parada k em 1300 + 60k com intervalo de 30 s entre posicoes,
    entao a decisao em s = 5 acontece em 1600 + 30 = 1630. C passa na parada 0
    (s - 5) em saida_c + 60k.
    """
    from ml import montar
    montar.spark = spark
    linhas = []
    for viagem, inicio, anterior, intervalo in (("A", 1000, "Z", 30), ("B", 1300, "A", 30),
                                                ("C", saida_c, "B", intervalo_c)):
        for k in range(16):
            t = inicio + 60 * k
            h = {"A": 600.0, "B": 300.0, "C": float(saida_c - 1300)}[viagem]
            linhas.append({
                "route_id": "r", "direction_id": 0, "stop_id": f"p{k}", "viagem_id": viagem, "faixa_horaria": "f",
                "stop_sequence": k, "vehicle_id": viagem, "onibus_anterior": anterior,
                "passagem_unix": float(t), "headway_s": h, "headway_valido": True, "h": h,
                "disponivel_unix": float(t + intervalo), "rotulavel": True,
                # So B em p15 chega colado: e o alvo do exemplo de B em p5.
                "colado": viagem == "B" and k == 15, "m_hist": 400.0,
            })
    b = spark.createDataFrame(linhas)
    x = montar.montar(montar.com_vizinhos(b))
    return x.where("viagem_id = 'B' and stop_sequence = 5").collect()[0]


def test_onibus_de_tras_conhecido_entra_com_o_intervalo_real(spark):
    r = viagens(spark, saida_c=1500)       # C conhecido em p0 as 1530 < 1630
    assert r["atras_censurado"] == 0
    assert r["atras_s"] == 200
    assert r["h_5"] == 300
    assert r["alvo_int"] == 1


def test_onibus_de_tras_ainda_nao_conhecido_vira_tempo_decorrido(spark):
    r = viagens(spark, saida_c=1610)       # C so e conhecido em p0 as 1640 > 1630
    assert r["atras_censurado"] == 1
    # O intervalo real (310 s) ainda nao existia para quem decide as 1630; entra
    # o tempo desde que B passou em p0 sem C confirmado.
    assert r["atras_s"] == 1630 - 1300


def test_lider_conhecido_depois_da_decisao_fica_fora(spark):
    from ml import montar
    montar.spark = spark
    # A passa em p5 as 1590, mas com intervalo de 60 s so e conhecido as 1650,
    # depois da decisao de B (1600 + 30).
    linhas = []
    for viagem, t, intervalo, anterior in (("A", 1590, 60, "Z"), ("B", 1600, 30, "A")):
        linhas.append({
            "route_id": "r", "direction_id": 0, "stop_id": "p5", "viagem_id": viagem, "faixa_horaria": "f",
            "stop_sequence": 5, "vehicle_id": viagem, "onibus_anterior": anterior,
            "passagem_unix": float(t), "headway_s": 500.0, "headway_valido": True, "h": 500.0,
            "disponivel_unix": float(t + intervalo), "rotulavel": True, "colado": False,
            "m_hist": 400.0,
        })
    x = montar.montar(montar.com_vizinhos(spark.createDataFrame(linhas)))
    r = x.where("viagem_id = 'B'").collect()[0]
    assert r["lider_h"] == 500.0
    assert r["lider_conhecido"] is False
