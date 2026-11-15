"""O PBIP versionado e exatamente o que powerbi/gerar_pbip.py gera.

Quem edita o TMDL ou um visual.json a mao (ou pelo Desktop, com Salvar) e
esquece de levar a mudanca para o gerador quebra este teste: na proxima
geracao a edicao sumiria. Python puro, sem banco e sem Desktop.
"""
import json
import re
import sys
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[1] / "powerbi"
sys.path.insert(0, str(PASTA))

import modelo  # noqa: E402
import relatorio  # noqa: E402

DEFINICAO = PASTA / "Radar.SemanticModel" / "definition"
PAGINAS = PASTA / "Radar.Report" / "definition" / "pages"
# O endereco do Neon fica real na pasta local (filtro git_censura) e marcador no Git: compara sem ele.
SERVIDOR = re.compile(r'(expression ServidorPostgres = )"[^"]*"')


def sem_servidor(texto: str) -> str:
    return SERVIDOR.sub(r'\1"X"', texto)


def test_tmdl_versionado_e_o_gerado():
    gerados = modelo.arquivos_modelo("X", "neondb")
    no_disco = {p.relative_to(DEFINICAO).as_posix() for p in DEFINICAO.rglob("*.tmdl")}
    assert no_disco == set(gerados), "arquivo TMDL sobrando ou faltando: rode python -I powerbi/gerar_pbip.py"
    diferentes = [rel for rel, texto in gerados.items()
                  if sem_servidor((DEFINICAO / rel).read_text(encoding="utf-8")) != sem_servidor(texto)]
    assert not diferentes, f"TMDL diferente do gerador: {diferentes}"


@pytest.fixture(scope="module")
def paginas():
    return relatorio.construir()


def test_paginas_versionadas_sao_as_geradas(paginas):
    no_disco = {p.name for p in PAGINAS.iterdir() if p.is_dir()}
    assert no_disco == {pg.nome for pg in paginas}
    ordem = json.loads((PAGINAS / "pages.json").read_text(encoding="utf-8"))["pageOrder"]
    assert ordem == [pg.nome for pg in paginas]
    for pg in paginas:
        assert json.loads((PAGINAS / pg.nome / "page.json").read_text(encoding="utf-8")) == pg.json_pagina(), pg.nome


def test_visuais_versionados_sao_os_gerados(paginas):
    diferentes = []
    for pg in paginas:
        pasta = PAGINAS / pg.nome / "visuals"
        assert {p.name for p in pasta.iterdir()} == {v["name"] for v in pg.visuais}, pg.nome
        for v in pg.visuais:
            if json.loads((pasta / v["name"] / "visual.json").read_text(encoding="utf-8")) != v:
                diferentes.append(f"{pg.nome}/{v['name']}")
    assert not diferentes, f"visual.json diferente do gerador: {diferentes}"


# ---------------------------------------------------------------------------
# Conferencia DAX x SQL (powerbi/conferencia/conferir.py): a parte que nao pede Desktop
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def conferir():
    import importlib.util
    spec = importlib.util.spec_from_file_location("conferir", PASTA / "conferencia" / "conferir.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_toda_metrica_do_sql_tem_medida_no_modelo(conferir):
    from painel.consultas import METRICAS
    nomes = {m[0] for m in modelo.medidas()}
    assert set(conferir.MEDIDAS) == set(METRICAS)
    assert set(conferir.MEDIDAS.values()) <= nomes


def test_casos_usam_so_filtros_conhecidos(conferir):
    casos = json.loads((PASTA / "conferencia" / "casos.json").read_text(encoding="utf-8"))["casos"]
    assert len({c["nome"] for c in casos}) == len(casos)
    for c in casos:
        assert set(c.get("agrupar", [])) <= set(conferir.COLUNAS), c["nome"]
        assert c.get("tipo_dia") in (None, "dia_util", "sabado", "domingo_feriado"), c["nome"]
        sql, params = conferir.sql_caso(c)
        assert c["de"] not in sql and params[0].isoformat() == c["de"]


def test_consulta_dax_filtra_e_pede_todas_as_medidas(conferir):
    q = conferir.consulta_dax({"nome": "x", "de": "2026-10-01", "ate": "2026-10-07", "tipo_dia": "sabado",
                               "alta_frequencia": False, "linhas": ['9"1'], "agrupar": ["route_id"]})
    assert q.startswith("EVALUATE\nSUMMARIZECOLUMNS (\n    dim_linha[route_id],")
    assert "DATE ( 2026, 10, 1 )" in q and "DATE ( 2026, 10, 7 )" in q
    assert 'TREATAS ( { "sabado" }, dim_tipo_dia[tipo_dia] )' in q
    assert 'TREATAS ( { "baixa" }, dim_frequencia[frequencia] )' in q
    assert 'TREATAS ( { "9""1" }, dim_linha[route_id] )' in q
    for m, medida in conferir.MEDIDAS.items():
        assert f'"{m}", [{medida}]' in q


def test_comparar_tolera_arredondamento_e_acusa_o_resto(conferir):
    caso = {"nome": "c", "agrupar": ["route_id"]}
    base = {m: 1.0 for m in conferir.MEDIDAS}
    sql = [{"route_id": "a", **base}, {"route_id": "b", **base}, {"route_id": "c", **base}]
    dax = [{"dim_linha[route_id]": "a", **{f"[{m}]": "1.0000000000001" for m in base}},
           {"dim_linha[route_id]": "b", **{f"[{m}]": "1" for m in base}, "[excesso_min]": "1.01"},
           {"dim_linha[route_id]": "d", **{f"[{m}]": "1" for m in base}}]
    n, erros = conferir.comparar(caso, dax, sql)
    assert n == 2 * len(base)
    assert erros == ["c: ('c',) so no SQL", "c: ('d',) so no DAX", "c: ('b',) excesso_min DAX=1.01 SQL=1.0"]
