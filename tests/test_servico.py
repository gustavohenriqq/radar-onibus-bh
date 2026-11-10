"""Exportacao para o banco do painel.

Os testes de janela e de tabela sao Python puro. Os de metricas pedem Spark e
rodam no conteiner radar-spark:dev (pulados onde nao ha pyspark).
"""
from datetime import date

import pytest

from servico.exportar import DATA_INICIO, TABELAS, apagar, colunas, ddl, janela


def test_janela_recalcula_os_ultimos_dias_e_28_de_paradas():
    assert janela(date(2026, 11, 9), 3, False) == (date(2026, 11, 7), date(2026, 11, 9), date(2026, 10, 13))


def test_janela_nunca_comeca_antes_do_primeiro_dia_cheio():
    assert janela(date(2026, 9, 16), 3, False) == (DATA_INICIO, date(2026, 9, 16), DATA_INICIO)
    assert janela(date(2026, 11, 9), 3, True)[0] == DATA_INICIO


def test_colunas_saem_do_ddl_na_ordem():
    assert colunas("linhas") == ["route_id", "route_long_name"]
    assert colunas("linha_dia_faixa")[:7] == [
        "route_id", "direction_id", "data_bh", "faixa_horaria", "ordem_faixa", "tipo_dia", "alta_frequencia"]


def test_tabela_por_dia_apaga_so_a_janela_e_as_outras_tudo():
    for t, (_, chave, modo) in TABELAS.items():
        assert ddl(t).endswith(f"primary key ({chave}))")
        if modo == "janela":
            assert "data_bh" in colunas(t) and "between" in apagar(t)
        else:
            assert "where" not in apagar(t)


@pytest.fixture(scope="module")
def spark():
    pytest.importorskip("pyspark")
    pytest.importorskip("delta")
    from silver.processar import sessao
    s = sessao("1g")
    yield s


def test_somas_reagregadas_dao_as_mesmas_metricas_dos_grupos(spark):
    from servico.metricas import SOMAS, metricas, preparar, somar
    # Cinco grupos de parada em duas linhas e dois dias, com var_passagem nula num deles.
    linhas = [
        ("r1", 0, "p1", "2026-10-01", "pico", 1, 5, 3000.0, 4.0e5, 1, 0, 1.0e4, 1, 0, 0, 900.0),
        ("r1", 0, "p2", "2026-10-01", "pico", 1, 3, 1500.0, 1.0e5, 0, 0, 0.0, 0, 0, 0, None),
        ("r1", 0, "p1", "2026-10-02", "pico", 1, 8, 6000.0, 9.0e5, 2, 1, 3.0e4, 2, 0, 0, 400.0),
        ("r2", 1, "p9", "2026-10-01", "noite", 2, 4, 4800.0, 2.0e5, 0, 0, 0.0, 0, 0, 0, 100.0),
        ("r2", 1, "p8", "2026-10-02", "noite", 2, 6, 3600.0, 7.0e5, 3, 2, 5.0e4, 1, 1, 1, 50.0),
    ]
    cols = ["route_id", "direction_id", "stop_id", "data_bh", "faixa_horaria", "ordem_faixa", "n", "soma",
            "dev2", "colados", "abaixo_60s", "reducao", "pares", "pulo_primeiro", "pulo_colado", "var_passagem"]
    gr = preparar(spark.createDataFrame(linhas, cols))
    banco = somar(gr, ["route_id", "direction_id", "data_bh", "faixa_horaria", "ordem_faixa"])
    assert set(SOMAS) <= set(banco.columns)
    for chaves in ([], ["route_id"], ["data_bh"], ["faixa_horaria", "ordem_faixa"]):
        direto = sorted(map(tuple, metricas(gr, chaves).collect()))
        reagregado = sorted(map(tuple, metricas(banco, chaves).collect()))
        assert direto == reagregado, chaves
    # Uma conta a mao: excesso da rede = soma(dev2) / 2 / soma(soma) / 60.
    rede = metricas(gr, []).first()
    assert rede["excesso_min"] == round(2.3e6 / 2 / 18900 / 60, 3)
    assert rede["regular_min"] == round((3000**2 / 5 + 1500**2 / 3 + 6000**2 / 8 + 4800**2 / 4 + 3600**2 / 6)
                                        / 2 / 18900 / 60, 3)


def test_url_vem_do_ambiente_ou_do_env_do_projeto(tmp_path, monkeypatch):
    from servico.exportar import url_do_banco
    env = tmp_path / ".env"
    env.write_text("BACKUP_PAR_URL=x\nNEON_URL=postgresql://u:p@h/db?sslmode=require&channel_binding=require\n")
    monkeypatch.delenv("NEON_URL", raising=False)
    assert url_do_banco(str(env)).endswith("&channel_binding=require")
    monkeypatch.setenv("NEON_URL", "postgresql://outro")
    assert url_do_banco(str(env)) == "postgresql://outro"
    monkeypatch.delenv("NEON_URL")
    assert url_do_banco(str(tmp_path / "nao_existe")) == ""
