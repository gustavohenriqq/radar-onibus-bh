"""Consultas do painel sobre o banco de servico (Neon, esquema radar).

As formulas sao as de servico/metricas.py, escritas em SQL sobre as SOMAS de
radar.linha_dia_faixa. Sem arredondar: quem mostra formata, e a conciliacao
compara com tolerancia de meia casa decimal contra os CSVs da analise.
"""
from datetime import date

ESQUEMA = "radar"

# Metrica: (expressao SQL sobre as somas, casas decimais na analise).
METRICAS = {
    "grupos": ("sum(grupos)", 0),
    "headways": ("sum(n)", 0),
    "horas": ("sum(soma) / 3600", 1),
    "regular_min": ("sum(soma2_n) / 2 / sum(soma) / 60", 3),
    "excesso_min": ("sum(dev2) / 2 / sum(soma) / 60", 3),
    "volume_min_h": ("sum(dev2) / 2 / 60 / 3600", 1),
    "colados_pct": ("sum(colados)::float8 / sum(n)::float8", 4),
    "abaixo_60s_pct": ("sum(abaixo_60s)::float8 / sum(n)::float8", 4),
    "reducao_pct": ("sum(reducao) / nullif(sum(dev2), 0)", 4),
    "pares": ("sum(pares)", 0),
    "pulo_primeiro": ("sum(pulo_primeiro)", 0),
    "pulo_colado": ("sum(pulo_colado)", 0),
    "vies_min": ("sum(var_n) / sum(soma) / 60", 3),
    "vies_pct": ("sum(var_n) / nullif(sum(dev2) / 2, 0)", 4),
}

# Colunas de linha_dia_faixa que podem agrupar ou filtrar.
DIMENSOES = {"route_id", "direction_id", "data_bh", "faixa_horaria", "ordem_faixa", "tipo_dia", "alta_frequencia"}


def filtro(de: date, ate: date, tipo_dia: str | None = None, alta_frequencia: bool | None = None,
           linhas: list[str] | None = None) -> tuple[str, list]:
    """Clausula where e parametros. Valores sempre por parametro, nunca no texto."""
    partes, params = ["data_bh between %s and %s"], [de, ate]
    if tipo_dia:
        partes.append("tipo_dia = %s")
        params.append(tipo_dia)
    if alta_frequencia is not None:
        partes.append("alta_frequencia = %s")
        params.append(alta_frequencia)
    if linhas:
        partes.append("route_id = any(%s)")
        params.append(list(linhas))
    return " and ".join(partes), params


def filtro_paradas(tipo_dia: str | None = None, alta_frequencia: bool | None = None) -> tuple[str, list]:
    """Como filtro(), sem datas: radar.paradas_28d ja e a janela fixa de 28 dias."""
    partes, params = ["true"], []
    if tipo_dia:
        partes.append("tipo_dia = %s")
        params.append(tipo_dia)
    if alta_frequencia is not None:
        partes.append("alta_frequencia = %s")
        params.append(alta_frequencia)
    return " and ".join(partes), params


def _colunas_metricas() -> str:
    return ", ".join(f"{expr} as {nome}" for nome, (expr, _) in METRICAS.items())


def sql_paradas(onde: str) -> str:
    """Metricas por parada, com nome e posicao. Parametro extra no fim: horas minimas."""
    return (f"select stop_id, max(stop_name) as stop_name, max(stop_lat) as lat, max(stop_lon) as lon, "
            f"min(janela_ini) as janela_ini, max(janela_fim) as janela_fim, {_colunas_metricas()} "
            f"from {ESQUEMA}.paradas_28d where {onde} group by stop_id having sum(soma) / 3600 >= %s")


def sql_hist(onde: str) -> str:
    """Intervalos por classe de H/m (0,05 cada; a 80 junta 4 ou mais). Sem recorte por linha."""
    return (f"select classe, sum(headways) as headways from {ESQUEMA}.hist_dia "
            f"where {onde} group by classe order by classe")


SQL_ML = (f"select data_bh, sum(exemplos) as exemplos, sum(positivos) as positivos, "
          f"sum(alertas) as alertas, sum(acertos) as acertos, max(limiar) as limiar "
          f"from {ESQUEMA}.ml_resumo where conjunto = 'teste' group by data_bh order by data_bh")

SQL_CARGA = f"select carregado_em, de, ate from {ESQUEMA}.cargas order by carregado_em desc limit 1"

SQL_LINHAS = f"select route_id, route_long_name from {ESQUEMA}.linhas order by route_id"

SQL_QUALIDADE = (f"select data_bh, passagens, cobertura_passagens, headways, headways_validos, "
                 f"headways_feed_parado, linhas from {ESQUEMA}.qualidade_diaria order by data_bh")


def sql_metricas(chaves: list[str], onde: str, tabela: str = "linha_dia_faixa") -> str:
    """Metricas por chaves sobre a tabela de somas (linha_dia_faixa ou paradas_28d)."""
    desconhecidas = set(chaves) - DIMENSOES - {"stop_id"}
    if desconhecidas:
        raise ValueError(f"chave fora da lista: {sorted(desconhecidas)}")
    cols = [f"{expr} as {nome}" for nome, (expr, _) in METRICAS.items()]
    sel = ", ".join(chaves + cols)
    grupo = f" group by {', '.join(chaves)} order by {', '.join(chaves)}" if chaves else ""
    return f"select {sel} from {ESQUEMA}.{tabela} where {onde}{grupo}"


# ---------------------------------------------------------------------------
# Somas cruas: o painel agrega em pandas e calcula as metricas com metricas(),
# a mesma conta de METRICAS. Uma consulta serve varios quadros da mesma pagina.
# ---------------------------------------------------------------------------
SOMAS = ["grupos", "n", "soma", "soma2_n", "dev2", "colados", "abaixo_60s", "reducao", "pares",
         "pulo_primeiro", "pulo_colado", "var_n"]
# Chave -> expressao SQL (dia_semana: 1 = segunda ... 7 = domingo, como WEEKDAY ( , 2 ) no Power BI)
CHAVES_SOMAS = {c: c for c in DIMENSOES} | {"dia_semana": "extract(isodow from data_bh)::int"}


def sql_somas(chaves: list[str], onde: str) -> str:
    """Somas reagregaveis de linha_dia_faixa por chaves da lista (nada vem do usuario no texto)."""
    desconhecidas = set(chaves) - set(CHAVES_SOMAS)
    if desconhecidas:
        raise ValueError(f"chave fora da lista: {sorted(desconhecidas)}")
    cols = [f"{CHAVES_SOMAS[c]} as {c}" for c in chaves] + [f"sum({s})::float8 as {s}" for s in SOMAS]
    grupo = f" group by {', '.join(CHAVES_SOMAS[c] for c in chaves)}" if chaves else ""
    return f"select {', '.join(cols)} from {ESQUEMA}.linha_dia_faixa where {onde}{grupo}"


def metricas(df):
    """As metricas de METRICAS sobre um DataFrame de somas (uma linha por grupo). Devolve uma copia."""
    import numpy as np
    d = df.copy()
    soma = d["soma"].replace(0, np.nan)
    n = d["n"].replace(0, np.nan)
    dev2 = d["dev2"].replace(0, np.nan)
    d["headways"] = d["n"]
    d["horas"] = d["soma"] / 3600
    d["regular_min"] = d["soma2_n"] / 2 / soma / 60
    d["excesso_min"] = d["dev2"] / 2 / soma / 60
    d["media_min"] = d["regular_min"] + d["excesso_min"]
    d["volume_min_h"] = d["dev2"] / 2 / 60 / 3600
    d["colados_pct"] = d["colados"] / n
    d["abaixo_60s_pct"] = d["abaixo_60s"] / n
    d["reducao_pct"] = d["reducao"] / dev2
    d["vies_min"] = d["var_n"] / soma / 60
    d["vies_pct"] = d["var_n"] / (dev2 / 2)
    comboio = d["pares"] + d["pulo_primeiro"] + d["pulo_colado"]
    d["comboio_pct"] = d["pulo_colado"] / comboio.replace(0, np.nan)
    return d


def total(df):
    """Soma as somas de todas as linhas e devolve uma Series com as metricas (vazia se nao houver dado)."""
    import pandas as pd
    if df is None or df.empty or not df["n"].sum():
        return None
    return metricas(pd.DataFrame([df[SOMAS].sum()])).iloc[0]


def agrega(df, chaves: list[str]):
    """Reagrega as somas por outras chaves e calcula as metricas."""
    return metricas(df.groupby(chaves, as_index=False, sort=False)[SOMAS].sum())


# Somas por ponto (ultimos 28 dias), sem corte de horas: o corte do mapa e feito no painel.
SOMAS_PARADA = ["n", "soma", "soma2_n", "dev2", "colados"]


def sql_paradas_somas(onde: str) -> str:
    cols = ", ".join(f"sum({s})::float8 as {s}" for s in SOMAS_PARADA)
    return (f"select stop_id, max(stop_name) as stop_name, max(stop_lat) as lat, max(stop_lon) as lon, "
            f"max(linhas) as linhas, min(janela_ini) as janela_ini, max(janela_fim) as janela_fim, {cols} "
            f"from {ESQUEMA}.paradas_28d where {onde} group by stop_id")


SQL_ML_LINHAS = (f"select data_bh, route_id, sum(exemplos)::float8 as exemplos, sum(positivos)::float8 as positivos, "
                 f"sum(alertas)::float8 as alertas, sum(acertos)::float8 as acertos, max(limiar) as limiar "
                 f"from {ESQUEMA}.ml_resumo where conjunto = 'teste' group by data_bh, route_id")
