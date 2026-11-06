"""Comparacao das impressoes digitais da Gold (sem Spark)."""

from gold.digitais import igual


def dia(n=10, h="123", **f):
    return {"n": n, "h": h, "f": f or {"media": [50.44532318376070, 1234.5]}}


def test_ruido_de_ponto_flutuante_nao_conta_como_diferenca():
    assert igual(dia(), dia(media=[50.44532318376069, 1234.5000000000002]))


def test_valor_decimal_que_mudou_conta():
    assert not igual(dia(), dia(media=[50.4454, 1234.5]))


def test_valor_trocado_de_linha_muda_a_soma_ponderada():
    assert not igual(dia(), dia(media=[50.44532318376070, 1240.0]))


def test_contagem_ou_hash_diferente_conta():
    assert not igual(dia(), dia(n=11))
    assert not igual(dia(), dia(h="124"))


def test_dia_que_falta_numa_das_fotos_conta():
    assert not igual(dia(), None)
    assert igual(None, None)
