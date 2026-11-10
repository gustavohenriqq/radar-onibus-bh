"""Painel publico do radar-onibus-bh (Streamlit).

Le o banco de servico (Neon, esquema radar) com o usuario so leitura. As contas
sao as de painel/consultas.py, as mesmas que a conciliacao confere contra os
CSVs da analise. Rodar da raiz do repositorio:

    streamlit run painel/app.py

A URL do banco vem de st.secrets["PAINEL_URL"] (Streamlit Cloud) ou do .env
local (PAINEL_URL=...). Nunca a NEON_URL, que escreve.
"""
import logging
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import psycopg
import pydeck as pdk
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from painel.consultas import (SQL_CARGA, SQL_LINHAS, SQL_ML, SQL_QUALIDADE, filtro, filtro_paradas,  # noqa: E402
                              sql_hist, sql_metricas, sql_paradas)
from painel.formato import br, data_br, pct  # noqa: E402

BH = ZoneInfo("America/Sao_Paulo")
INICIO = date(2026, 9, 15)
ANALISE = (date(2026, 9, 15), date(2026, 11, 5))
REPO = "https://github.com/gustavohenriqq/radar-onibus-bh"
HORAS_MIN_PARADA = 25  # na janela de 28 dias (a analise usou 50 h em 52 dias)

# Paleta Midnight Atlas.
FUNDO, PAINEL, BORDA = "#0A1024", "#0F1839", "rgba(148,163,255,.14)"
TEXTO, SUAVE, APAGADO, GRADE = "#F2F5FF", "#B8C2E6", "#8E99C6", "rgba(148,163,255,.12)"
CIANO, VIOLETA, MENTA, CORAL, DOURADO = "#22D3EE", "#8B7CF6", "#34D399", "#FB7185", "#F5B83D"

TIPOS_DIA = {"dia_util": "Dia útil", "sabado": "Sábado", "domingo_feriado": "Domingo e feriado", "todos": "Todos"}
TIPOS_DIA_FRASE = {"dia_util": "em dia útil", "sabado": "no sábado", "domingo_feriado": "no domingo e feriado",
                   "todos": "em todos os tipos de dia"}
FREQS = {"alta": "Alta (até 15 min)", "baixa": "Baixa", "todas": "Todas"}
FREQ_VALOR = {"alta": True, "baixa": False, "todas": None}
PERIODOS = {"tudo": "Tudo desde 15/09", "28d": "Últimos 28 dias", "7d": "Últimos 7 dias",
            "analise": "Janela da análise (15/09 a 05/11)", "datas": "Escolher datas"}
FAIXAS = {"madrugada": "Madrugada<br>0 h a 4 h", "inicio_manha": "Início da manhã<br>5 h",
          "pico_manha": "Pico da manhã<br>6 h a 8 h", "entre_picos": "Entre picos<br>9 h a 15 h",
          "pico_tarde": "Pico da tarde<br>16 h a 19 h", "noite": "Noite<br>20 h a 23 h"}


# ---------- banco ----------

class BancoFora(Exception):
    """O banco nao respondeu nesta rodada; os quadros seguintes desistem na hora."""


def url_banco() -> str | None:
    try:
        if "PAINEL_URL" in st.secrets:
            return st.secrets["PAINEL_URL"]
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    return os.environ.get("PAINEL_URL")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=500)
def consultar(sql: str, params: tuple) -> pd.DataFrame:
    """Uma conexao por pedido, aberta e fechada aqui. Cache de 1 h por (consulta, filtros)."""
    with psycopg.connect(url_banco(), connect_timeout=30, application_name="painel") as con:
        con.execute("set jit = off")
        cur = con.execute(sql, list(params))
        cols = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    for c in df.columns:  # numeric do Postgres chega como Decimal
        if df[c].map(lambda v: isinstance(v, Decimal)).any():
            df[c] = df[c].astype(float)
    return df


def dados(sql: str, params=()) -> pd.DataFrame:
    if st.session_state.get("banco_fora"):
        raise BancoFora
    if not url_banco():  # segredo PAINEL_URL ausente: mesmo aviso de banco fora, sem traceback
        logging.error("PAINEL_URL nao configurada")
        st.session_state.banco_fora = True
        raise BancoFora
    try:
        with st.spinner("Consultando o banco. Na primeira visita ele pode levar até 1 minuto para acordar."):
            return consultar(sql, tuple(params))
    except psycopg.OperationalError:
        st.session_state.banco_fora = True
        raise BancoFora


def quadro(func):
    """Cada visual carrega separado: se o banco cair, os outros quadros continuam de pe.
    Qualquer outra falha (permissao, tabela) derruba so o quadro, sem traceback ao publico."""
    try:
        func()
    except BancoFora:
        st.info("Este quadro volta quando o banco responder.")
    except Exception:
        logging.exception("quadro %s falhou", getattr(func, "__name__", "?"))
        st.warning("Este quadro não carregou agora. Os outros seguem valendo.")


# ---------- aparencia ----------

CSS = f"""
<style>
.stApp {{ background: radial-gradient(1200px 600px at 10% -10%, rgba(34,211,238,.10), transparent 60%),
          radial-gradient(900px 500px at 100% 0%, rgba(139,124,246,.12), transparent 60%), {FUNDO}; }}
.block-container {{ padding-top: 3.6rem; max-width: 1400px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3 {{ color: {TEXTO}; letter-spacing: -.01em; }}
.olho {{ color: {DOURADO}; font-size: .8rem; font-weight: 700; letter-spacing: .14em; margin: 2.2rem 0 .1rem; }}
.titulo {{ color: {TEXTO}; font-size: 1.6rem; font-weight: 700; margin: 0 0 .3rem; }}
.nota {{ color: {SUAVE}; font-size: .95rem; margin: 0 0 .8rem; }}
.marca {{ font-size: 2.6rem !important; font-weight: 800; color: {TEXTO}; margin: 0; line-height: 1.1; }}
.marca span {{ color: {CIANO}; }}
.selo {{ display: inline-block; border: 1px solid {BORDA}; background: {PAINEL}; color: {SUAVE};
         border-radius: 999px; padding: .25rem .8rem; font-size: .85rem; margin-top: .5rem; }}
.manchete {{ color: {TEXTO}; font-size: 1.35rem; line-height: 1.5; margin: .6rem 0 1rem; max-width: 62rem; }}
.manchete b {{ color: {CORAL}; }}
.card {{ background: linear-gradient(180deg, rgba(24,34,78,.78), rgba(12,18,44,.78)); border: 1px solid {BORDA};
         border-radius: 20px; padding: 1rem 1.2rem; height: 100%; }}
.card .rotulo {{ color: {SUAVE}; font-size: .9rem; }}
.card .valor {{ font-size: 2.3rem; font-weight: 800; line-height: 1.2; }}
.card .sub {{ color: {APAGADO}; font-size: .85rem; }}
[data-testid="stHorizontalBlock"] + div [data-testid="stCaptionContainer"] {{ margin-top: .6rem; }}
</style>
"""


def card(rotulo: str, valor: str, sub: str, cor: str) -> str:
    return (f'<div class="card"><div class="rotulo">{rotulo}</div>'
            f'<div class="valor" style="color:{cor}">{valor}</div><div class="sub">{sub}</div></div>')


def cards(itens):
    for col, item in zip(st.columns(len(itens)), itens):
        col.markdown(card(*item), unsafe_allow_html=True)


def titulo(olho: str, texto: str, nota: str = ""):
    st.markdown(f'<div class="olho">{olho}</div><div class="titulo">{texto}</div>'
                + (f'<div class="nota">{nota}</div>' if nota else ""), unsafe_allow_html=True)


def estilo(fig: go.Figure, altura: int = 380) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, Segoe UI, sans-serif", color=SUAVE, size=14), separators=",.",
                      margin=dict(l=10, r=10, t=40, b=10), height=altura, hoverlabel=dict(font_size=14),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=TEXTO)))
    fig.update_xaxes(gridcolor=GRADE, zeroline=False)
    fig.update_yaxes(gridcolor=GRADE, zeroline=False)
    return fig


def grafico(fig: go.Figure):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "locale": "pt-BR"})


# ---------- filtros (no endereco, para o link reproduzir a visao) ----------

def ler_endereco():
    if st.session_state.get("_endereco_lido"):
        return
    q = st.query_params
    if q.get("periodo") in PERIODOS:
        st.session_state.periodo = q["periodo"]
    if q.get("dia") in TIPOS_DIA:
        st.session_state.dia = q["dia"]
    if q.get("freq") in FREQS:
        st.session_state.freq = q["freq"]
    if q.get("linhas"):
        st.session_state.linhas_pedidas = [x for x in q["linhas"].split(",") if x]
    try:
        if q.get("de") and q.get("ate"):
            st.session_state.datas = (date.fromisoformat(q["de"]), date.fromisoformat(q["ate"]))
    except ValueError:
        pass
    st.session_state._endereco_lido = True


def gravar_endereco(periodo, de, ate, dia, freq, linhas):
    q = {"periodo": periodo, "dia": dia, "freq": freq}
    if periodo == "datas":
        q.update(de=de.isoformat(), ate=ate.isoformat())
    if linhas:
        q["linhas"] = ",".join(linhas)
    if dict(st.query_params) != q:
        st.query_params.from_dict(q)


def intervalo(periodo: str, ultimo: date) -> tuple[date, date]:
    if periodo == "28d":
        return max(INICIO, ultimo - timedelta(days=27)), ultimo
    if periodo == "7d":
        return max(INICIO, ultimo - timedelta(days=6)), ultimo
    if periodo == "analise":
        return ANALISE
    return INICIO, ultimo


# ---------- quadros ----------

def q_manchete(f, nomes):
    onde, params = f["onde"], f["params"]
    rede = dados(sql_metricas([], onde), params)
    if rede.empty or pd.isna(rede.iloc[0]["headways"]):
        st.warning("Nenhum intervalo medido com esses filtros. Tente outro período ou tipo de dia.")
        return
    r = rede.iloc[0]
    reg, ext = r["regular_min"], r["excesso_min"]
    quem = ("nas linhas escolhidas" if f["linhas"] else
            {"alta": "numa linha de alta frequência", "baixa": "numa linha de baixa frequência",
             "todas": "numa linha qualquer"}[f["freq"]])
    st.markdown(
        f'<div class="manchete">{TIPOS_DIA_FRASE[f["dia"]].capitalize()}, quem chega ao ponto {quem} espera em média '
        f'<b>{br(reg + ext)} minutos</b> pelo ônibus. Com os mesmos ônibus passando em intervalos iguais, seriam '
        f'{br(reg)} minutos. A diferença, <b>{br(ext)} minutos (+{br(100 * ext / reg, 0)}%)</b>, '
        f'é o custo da irregularidade.</div>', unsafe_allow_html=True)
    cards([
        ("Espera média no ponto", f"{br(reg + ext)} min", "o que o passageiro espera hoje", TEXTO),
        ("Com ônibus regulares", f"{br(reg)} min", "metade do intervalo médio", CIANO),
        ("Espera extra", f"{br(ext)} min", f"+{br(100 * ext / reg, 0)}% pela irregularidade", CORAL),
        ("Ônibus colados", pct(r["colados_pct"]), "intervalo abaixo de 1/4 do médio", DOURADO),
    ])
    st.caption(f"{br(r['headways'], 0)} intervalos medidos em {br(r['horas'], 0)} horas de serviço, "
               f"de {data_br(f['de'])} a {data_br(f['ate'])}. Média ponderada pelo tempo de serviço coberto.")


def q_faixa(f):
    titulo("02 · HORA DO DIA", "Espera por faixa horária",
           "Espera média no ponto por faixa horária, em minutos")
    df = dados(sql_metricas(["ordem_faixa", "faixa_horaria"], f["onde"]), f["params"])
    if df.empty:
        st.info("Sem dados nesse recorte.")
        return
    x = [FAIXAS.get(v, v) for v in df["faixa_horaria"]]
    fig = go.Figure()
    fig.add_bar(x=x, y=df["regular_min"], name="Com ônibus regulares", marker_color=CIANO,
                hovertemplate="%{y:.2f} min<extra>regular</extra>")
    fig.add_bar(x=x, y=df["excesso_min"], name="Espera extra", marker_color=CORAL,
                text=[f"+{br(v, 1)}" for v in df["excesso_min"]], textposition="outside",
                textfont=dict(color=TEXTO, size=14), hovertemplate="%{y:.2f} min<extra>extra</extra>")
    fig.update_layout(barmode="stack", bargap=.35)
    fig.update_yaxes(title=None, rangemode="tozero")
    grafico(estilo(fig))


def q_tendencia(f):
    titulo("03 · DIA A DIA", "Espera extra por dia", "Minutos por passageiro em cada dia do período")
    df = dados(sql_metricas(["data_bh"], f["onde"]), f["params"])
    if df.empty:
        st.info("Sem dados nesse recorte.")
        return
    fig = go.Figure()
    fig.add_scatter(x=df["data_bh"], y=df["regular_min"], name="Com ônibus regulares", mode="lines+markers",
                    line=dict(color=CIANO, width=2), marker=dict(size=6), hovertemplate="%{y:.2f} min<extra></extra>")
    fig.add_scatter(x=df["data_bh"], y=df["excesso_min"], name="Espera extra", mode="lines+markers",
                    line=dict(color=CORAL, width=3), marker=dict(size=7), hovertemplate="%{y:.2f} min<extra></extra>")
    fig.update_xaxes(tickformat="%d/%m", hoverformat="%a %d/%m")
    fig.update_yaxes(rangemode="tozero")
    fig.update_layout(hovermode="x unified")
    grafico(estilo(fig, 340))


def q_linhas(f, nomes):
    titulo("04 · LINHAS", "Onde está a espera extra",
           "Ordem pelo volume: espera extra vezes horas de serviço. "
           "Uma linha sobe por ser irregular, por rodar muito, ou pelos dois")
    onde, params = filtro(f["de"], f["ate"], f["tipo_dia"], f["alta"])  # rede inteira, para o % da rede
    df = dados(sql_metricas(["route_id"], onde), params)
    if df.empty:
        st.info("Sem dados nesse recorte.")
        return
    df["parte"] = df["volume_min_h"] / df["volume_min_h"].sum()
    df = df.sort_values("volume_min_h", ascending=False)
    df["posicao"] = range(1, len(df) + 1)
    if f["linhas"]:
        total = len(df)
        df = df[df["route_id"].isin(f["linhas"])]
        rotulo = (f"Linhas escolhidas, com a posição entre as {total} da rede. Juntas somam "
                  f"{pct(df['parte'].sum())} da espera extra da rede")
    else:
        top = df.head(20)
        rotulo = (f"As 20 primeiras de {len(df)} linhas somam {pct(top['parte'].sum())} da espera extra da rede, "
                  f"com {pct(top['horas'].sum() / df['horas'].sum())} das horas de serviço")
        df = top
    st.caption(rotulo)
    tabela = pd.DataFrame({
        "Posição": df["posicao"], "Linha": df["route_id"], "Nome": df["route_id"].map(nomes).fillna(""),
        "Regular (min)": df["regular_min"], "Extra (min)": df["excesso_min"], "% da espera extra": df["parte"],
        "Colados": df["colados_pct"], "Corte sem colagem": df["reducao_pct"], "Horas de serviço": df["horas"],
    })
    fmt = {"Regular (min)": lambda v: br(v, 2), "Extra (min)": lambda v: br(v, 2),
           "% da espera extra": lambda v: pct(v), "Colados": lambda v: pct(v),
           "Corte sem colagem": lambda v: pct(v), "Horas de serviço": lambda v: br(v, 0)}
    st.dataframe(tabela.style.format(fmt), hide_index=True, width="stretch",
                 height=min(35 * (len(tabela) + 1) + 3, 780))
    st.caption("Corte sem colagem: quanto da espera extra da linha some se o ônibus atrasado, que puxou o de trás "
               "para colado, passasse no meio do caminho entre os dois. É o tamanho do problema dos colados, "
               "não o ganho garantido de uma técnica.")


def cor_escala(v: pd.Series) -> list:
    lo, hi = v.quantile(.05), v.quantile(.95)
    t = ((v - lo) / (hi - lo if hi > lo else 1)).clip(0, 1)
    paradas = [(0, (34, 211, 238)), (.5, (245, 184, 61)), (1, (251, 113, 133))]
    cores = []
    for x in t:
        (a, ca), (b, cb) = (paradas[0], paradas[1]) if x <= .5 else (paradas[1], paradas[2])
        k = (x - a) / (b - a)
        cores.append([int(ca[i] + k * (cb[i] - ca[i])) for i in range(3)] + [200])
    return cores


def q_mapa(f):
    titulo("05 · PONTOS", "Espera extra por ponto",
           f"Últimos 28 dias, pontos com pelo menos {HORAS_MIN_PARADA} horas de serviço. "
           "Este quadro não segue o período nem as linhas escolhidas")
    onde, params = filtro_paradas(f["tipo_dia"], f["alta"])
    df = dados(sql_paradas(onde), params + [HORAS_MIN_PARADA])
    if df.empty:
        st.info("Sem pontos nesse recorte.")
        return
    janela = f"de {data_br(df['janela_ini'].min())} a {data_br(df['janela_fim'].max())}"
    df = df.dropna(subset=["lat", "lon", "excesso_min"]).copy()
    df["cor"] = cor_escala(df["excesso_min"])
    df["raio"] = (df["horas"] ** .5) * 6
    df["txt"] = [f"{n}\nEspera extra: {br(e, 2)} min (regular {br(r, 2)})\nColados: {pct(c)}\n{br(h, 0)} h de serviço"
                 for n, e, r, c, h in zip(df["stop_name"], df["excesso_min"], df["regular_min"],
                                          df["colados_pct"], df["horas"])]
    camada = pdk.Layer("ScatterplotLayer", df[["lon", "lat", "cor", "raio", "txt"]], get_position=["lon", "lat"],
                       get_fill_color="cor", get_radius="raio", radius_min_pixels=2, radius_max_pixels=14,
                       pickable=True, stroked=False)
    vista = pdk.ViewState(latitude=-19.88, longitude=-43.96, zoom=11)
    st.pydeck_chart(pdk.Deck(layers=[camada], initial_view_state=vista, map_style="dark",
                             tooltip={"text": "{txt}"}), height=560)
    st.caption(f"{br(len(df), 0)} pontos, {janela}. Cor: espera extra por passageiro, do ciano (menor) ao coral (maior). "
               "Tamanho: horas de serviço.")
    df["volume"] = df["volume_min_h"]
    top = df.sort_values("volume", ascending=False).head(10)
    st.markdown(f'<div class="nota">Os 10 pontos que mais somam espera extra respondem por '
                f'{pct(top["volume"].sum() / df["volume"].sum())} da espera extra dos pontos do mapa, com '
                f'{pct(top["horas"].sum() / df["horas"].sum())} das horas de serviço</div>', unsafe_allow_html=True)
    tabela = pd.DataFrame({"Ponto": top["stop_name"], "Regular (min)": top["regular_min"],
                           "Extra (min)": top["excesso_min"], "Colados": top["colados_pct"],
                           "Horas de serviço": top["horas"]})
    st.dataframe(tabela.style.format({"Regular (min)": lambda v: br(v, 2), "Extra (min)": lambda v: br(v, 2),
                                      "Colados": lambda v: pct(v), "Horas de serviço": lambda v: br(v, 0)}),
                 hide_index=True, width="stretch")


def q_colados(f):
    titulo("06 · ÔNIBUS COLADOS", "Dois ônibus da mesma linha quase juntos",
           "Colado: intervalo menor que 1/4 do intervalo médio daquela linha, naquele ponto, dia e faixa")
    r = dados(sql_metricas([], f["onde"]), f["params"]).iloc[0]
    if pd.isna(r["headways"]):
        st.info("Sem dados nesse recorte.")
        return
    colados = r["pares"] + r["pulo_primeiro"] + r["pulo_colado"]
    cards([
        ("Intervalos colados", pct(r["colados_pct"]), "dos intervalos medidos", DOURADO),
        ("Abaixo de 60 segundos", pct(r["abaixo_60s_pct"]), "praticamente juntos", CORAL),
        ("Corte sem colagem", pct(r["reducao_pct"]), "da espera extra, se o atrasado passasse no meio", MENTA),
        ("Colado atrás de colado", pct(r["pulo_colado"] / colados if colados else None),
         "dos colados: 3º ônibus em diante do comboio, fora da conta do corte", VIOLETA),
    ])
    onde, params = filtro(f["de"], f["ate"], f["tipo_dia"], f["alta"])
    h = dados(sql_hist(onde), params)
    if h.empty:
        return
    h["parte"] = h["headways"] / h["headways"].sum()
    x = [min(c, 80) * .05 + .025 for c in h["classe"]]
    cor = [CORAL if c < 5 else CIANO for c in h["classe"]]
    fig = go.Figure(go.Bar(x=x, y=h["parte"] * 100, marker_color=cor, width=.045,
                           customdata=[("4 ou mais" if c >= 80 else f"{br(c * .05, 2)} a {br(c * .05 + .05, 2)}")
                                       for c in h["classe"]],
                           hovertemplate="intervalo de %{customdata} vezes o médio<br>%{y:.2f}% dos intervalos"
                                         "<extra></extra>"))
    fig.add_vline(x=.25, line=dict(color=DOURADO, dash="dot"))
    fig.add_annotation(x=.25, y=1, yref="paper", text="1/4 do médio", showarrow=False, xanchor="left",
                       font=dict(color=DOURADO))
    fig.update_xaxes(title="intervalo dividido pelo intervalo médio", range=[0, 4.05], dtick=.5)
    fig.update_yaxes(title="% dos intervalos", ticksuffix="%")
    grafico(estilo(fig, 340))
    if f["linhas"]:
        st.caption("A distribuição é da rede inteira: o banco guarda o histograma por dia, sem separar por linha.")


def q_ml():
    titulo("07 · PREVISÃO", "Dá para avisar dez paradas antes?",
           "Modelo da fase 5 testado uma vez, fora da amostra, em dias úteis de alta frequência. Não roda todo dia")
    df = dados(SQL_ML)
    if df.empty:
        st.info("Sem resumo de previsão no banco.")
        return
    t = df[["exemplos", "positivos", "alertas", "acertos"]].sum()
    cards([
        ("Acerto dos alertas", pct(t["acertos"] / t["alertas"]), "dos ônibus apontados, chegaram colados", MENTA),
        ("Colados avisados", pct(t["acertos"] / t["positivos"]), "do total de colados no teste", CIANO),
        ("Sem modelo", pct(t["positivos"] / t["exemplos"]), "chance de um ônibus qualquer chegar colado", APAGADO),
        ("Alertas no teste", br(t["alertas"], 0), f"de {br(t['exemplos'], 0)} passagens", DOURADO),
    ])
    st.caption(f"Teste de {data_br(df['data_bh'].min())} a {data_br(df['data_bh'].max())}, limiar "
               f"{br(df['limiar'].max(), 3)} fixado na validação. O acerto passa dos 60% que um alerta precisa "
               "para se pagar, mas por pouco: o ganho estimado é de cerca de 1% do custo de nunca alertar. "
               "Uso sugerido: lista de prioridade para o controle, sem disparar ação.")


def q_qualidade():
    df = dados(SQL_QUALIDADE)
    if df.empty:
        return
    fig = go.Figure()
    fig.add_scatter(x=df["data_bh"], y=df["cobertura_passagens"] * 100, mode="lines+markers",
                    line=dict(color=CIANO), name="Passagens aproveitadas",
                    hovertemplate="%{y:.1f}%<extra></extra>")
    fig.update_yaxes(ticksuffix="%", range=[0, 100])
    fig.update_xaxes(tickformat="%d/%m")
    grafico(estilo(fig, 260))
    st.caption(f"{br(df['passagens'].sum(), 0)} passagens de ônibus por ponto reconstruídas das posições do feed. "
               "Uma queda indica feed parado ou falha de coleta naquele dia.")


# ---------- pagina ----------

def main():
    st.set_page_config(page_title="Radar de ônibus BH", page_icon="🚌", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.session_state.banco_fora = False  # cada rodada tenta o banco de novo uma vez
    aviso = st.empty()
    ler_endereco()

    ultimo = datetime.now(BH).date() - timedelta(days=1)
    selo = "Atualização diária"
    nomes = {}
    try:
        carga = dados(SQL_CARGA)
        if not carga.empty:
            c = carga.iloc[0]
            ultimo = c["ate"]
            selo = (f"Dados até {data_br(c['ate'])} · carregados em "
                    f"{c['carregado_em'].astimezone(BH).strftime('%d/%m às %H:%M')}")
        nomes = dict(dados(SQL_LINHAS).itertuples(index=False, name=None))
    except BancoFora:
        pass
    except Exception:  # cabecalho segue com a data pelo relogio
        logging.exception("carga ou linhas falhou")

    st.markdown(f'<div class="marca">Radar de <span>ônibus</span> BH</div><span class="selo">{selo}</span>',
                unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns([1.3, 1, 1, 2])
    periodo = c1.selectbox("Período", list(PERIODOS), format_func=PERIODOS.get, key="periodo")
    dia = c2.selectbox("Tipo de dia", list(TIPOS_DIA), format_func=TIPOS_DIA.get, key="dia")
    freq = c3.selectbox("Frequência da linha", list(FREQS), format_func=FREQS.get, key="freq",
                        help="Alta: intervalo médio de até 15 minutos na linha, sentido, dia e faixa. "
                             "Só aí vale a conta da espera: com ônibus de meia em meia hora, "
                             "o passageiro sai de casa no horário.")
    opcoes = sorted(nomes, key=lambda r: (len(r), r)) if nomes else st.session_state.get("linhas_pedidas", [])
    if "linhas_pedidas" in st.session_state:
        st.session_state.linhas = [x for x in st.session_state.pop("linhas_pedidas") if x in opcoes]
    linhas = c4.multiselect("Linhas", opcoes, key="linhas", placeholder="Rede inteira",
                            format_func=lambda r: f"{r} · {nomes.get(r, '')}".rstrip(" ·"))
    if periodo == "datas":
        d = st.session_state.get("datas")
        if isinstance(d, (tuple, list)) and d:  # datas da URL presas ao que o banco tem
            d = tuple(min(max(x, INICIO), ultimo) for x in d)
        if not d or d[0] > d[-1]:
            d = (max(INICIO, ultimo - timedelta(days=27)), ultimo)
        st.session_state.datas = d
        escolha = st.date_input("Datas", key="datas", min_value=INICIO, max_value=ultimo, format="DD/MM/YYYY")
        de, ate = (escolha[0], escolha[-1]) if isinstance(escolha, (tuple, list)) and escolha else (INICIO, ultimo)
    else:
        de, ate = intervalo(periodo, ultimo)
    gravar_endereco(periodo, de, ate, dia, freq, linhas)

    tipo_dia = None if dia == "todos" else dia
    alta = FREQ_VALOR[freq]
    onde, params = filtro(de, ate, tipo_dia, alta, linhas)
    f = dict(de=de, ate=ate, dia=dia, freq=freq, tipo_dia=tipo_dia, alta=alta, linhas=linhas,
             onde=onde, params=params)

    titulo("01 · MANCHETE", "Quanto o passageiro espera a mais por ônibus irregular")
    quadro(lambda: q_manchete(f, nomes))
    quadro(lambda: q_faixa(f))
    quadro(lambda: q_tendencia(f))
    quadro(lambda: q_linhas(f, nomes))
    quadro(lambda: q_mapa(f))
    quadro(lambda: q_colados(f))
    quadro(q_ml)

    with st.expander("Qualidade dos dados, dia a dia"):
        quadro(q_qualidade)
    with st.expander("Como a conta é feita"):
        st.markdown(
            "Quem chega ao ponto sem olhar o horário cai, com mais probabilidade, num intervalo longo, porque "
            "intervalos longos ocupam mais tempo do relógio. Com intervalos H entre ônibus de uma linha num ponto, "
            "a espera média é E[H²] / (2 E[H]) = E[H]/2 + Var(H) / (2 E[H]). O primeiro termo é a espera com ônibus "
            "regulares; o segundo, a espera extra pela irregularidade.\n\n"
            "Os intervalos saem das posições do feed GTFS-Realtime da Prefeitura de Belo Horizonte, coletadas por "
            "este projeto a cada 30 segundos desde 14/09/2026. O banco do painel guarda somas reagregáveis por "
            "linha, sentido, dia e faixa, então qualquer filtro dá a mesma conta da análise. Na janela da análise "
            f"(15/09 a 05/11), os números deste painel batem com os da [análise]({REPO}/blob/main/docs/analise.md).")
    st.caption(f"Código e método: [{REPO.removeprefix('https://')}]({REPO}). "
               "Dados: GTFS e GTFS-Realtime da PBH. Projeto independente, sem vínculo com a Prefeitura.")

    if st.session_state.banco_fora:
        with aviso.container():
            st.warning("O banco não respondeu. Ele dorme quando ninguém usa e leva até 1 minuto para acordar.")
            st.button("Tentar de novo", type="primary")


main()
