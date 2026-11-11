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

# Paleta noturna: ambar do letreiro, coral da espera extra, ciano do regular.
FUNDO, PAINEL, BORDA, BORDA_FORTE = "#060812", "#0E1430", "rgba(148,163,255,.14)", "rgba(148,163,255,.32)"
TEXTO, SUAVE, APAGADO, GRADE = "#E4E8F2", "#AEB6D2", "#8890B4", "rgba(148,163,255,.10)"
CIANO, VIOLETA, MENTA, CORAL, DOURADO = "#6FC1D3", "#A49AD6", "#72C3A2", "#E2828F", "#DDB06C"

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


def painel(chave: str, func):
    """Quadro dentro de um painel com classe propria (st-key-sec_*), estilizado no CSS."""
    with st.container(key=f"sec_{chave}"):
        quadro(func)


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
# Direcao: letreiro de onibus a noite. Marca, linhas e numeros em matriz de pontos ambar (Doto);
# numero gigante da espera extra em Archivo condensada com degrade coral; ruas animadas com os
# mesmos onibus em grupos e espacados; cada quadro com a sua cor de destaque.

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Doto:wght@600..900&display=swap');
:root {{ --fundo: {FUNDO}; --painel: {PAINEL}; --borda: {BORDA}; --texto: {TEXTO}; --suave: {SUAVE};
         --apagado: {APAGADO}; --ambar: {DOURADO}; --ciano: {CIANO}; --coral: {CORAL}; --violeta: {VIOLETA};
         --menta: {MENTA}; --curva: cubic-bezier(.2,.8,.2,1); }}
.stApp {{ background:
    radial-gradient(900px 620px at 104% -8%, rgba(226,130,143,.06), transparent 60%),
    radial-gradient(1000px 640px at -8% 0%, rgba(111,193,211,.05), transparent 60%),
    radial-gradient(1000px 700px at 50% 115%, rgba(164,154,214,.04), transparent 60%),
    radial-gradient(rgba(170,180,255,.035) 1px, transparent 1.3px) 0 0 / 24px 24px,
    var(--fundo); }}
.block-container {{ padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1380px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
@keyframes subir {{ from {{ opacity: 0; transform: translateY(18px); filter: blur(6px); }}
                    to {{ opacity: 1; transform: none; filter: none; }} }}
@keyframes crescer {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@keyframes surgir {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
@keyframes andar {{ from {{ transform: translateX(-50%); }} to {{ transform: translateX(0); }} }}
@keyframes rolar {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}

/* topo: letreiro de LED */
.topo {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: .9rem 1.4rem;
         margin-bottom: 1.1rem; }}
.topo .dir {{ display: flex; flex-wrap: wrap; align-items: center; gap: .6rem 1rem; }}
.letreiro {{ display: inline-flex; align-items: center; gap: .9rem; background: #030409;
             border: 1px solid #2A2410; border-radius: 14px; padding: .6rem 1.2rem .55rem .65rem;
             box-shadow: inset 0 0 0 4px #0A0B12; }}
.letreiro .placa {{ font-family: 'Doto', monospace; font-weight: 900; font-size: 2.2rem; line-height: 1;
                    color: #030409; background: var(--ambar); border-radius: 8px; padding: .3rem .5rem .2rem; }}
.letreiro .destino {{ font-family: 'Doto', monospace; font-weight: 800; font-size: 2.45rem; line-height: 1;
                      color: var(--ambar); letter-spacing: .02em; text-transform: uppercase; }}
.selo {{ display: inline-flex; align-items: center; gap: .55rem; color: var(--suave); font-size: .9rem;
         background: rgba(114,195,162,.06); border: 1px solid rgba(114,195,162,.22); border-radius: 99px;
         padding: .35rem .85rem; }}
.selo::before {{ content: ""; width: .55rem; height: .55rem; border-radius: 50%; background: var(--menta); }}
.topo a.git {{ color: var(--texto); text-decoration: none; font-size: .9rem; font-weight: 600;
               border: 1px solid var(--borda); border-radius: 99px; padding: .35rem .9rem; }}
.topo a.git:hover {{ border-color: var(--ciano); color: var(--ciano); }}

/* filtros: barra que acompanha a rolagem */
div:has(> .st-key-filtros) {{ position: sticky; top: 1.3rem; z-index: 60; padding-top: 2rem; margin-top: -2rem;
    background: linear-gradient(180deg, var(--fundo) 0, var(--fundo) 45%, transparent 100%); }}
.st-key-filtros {{ background: rgba(9,12,28,.86);
                   border: 1px solid var(--borda); border-radius: 18px; padding: .7rem 1rem .25rem;
                   backdrop-filter: blur(14px) saturate(150%); box-shadow: 0 18px 40px -26px rgba(0,0,0,.9); }}
.st-key-filtros label p {{ color: var(--ambar); font-size: .74rem; font-weight: 800; letter-spacing: .14em;
                          text-transform: uppercase; }}

/* hero: o numero da espera extra */
.st-key-hero {{ margin-top: 1.3rem; }}
.hero {{ position: relative; overflow: hidden; isolation: isolate; border-radius: 32px;
         padding: 2.6rem 2.8rem 1.5rem; border: 1px solid rgba(255,255,255,.08);
         background: linear-gradient(135deg, #15131F 0%, #0E1228 52%, #0C1820 100%);
         box-shadow: 0 30px 70px -50px rgba(0,0,0,.9), inset 0 1px 0 rgba(255,255,255,.05);
         animation: subir .8s var(--curva) both; }}
.hero::before {{ content: ""; position: absolute; inset: -60%; z-index: -2; opacity: .18; filter: blur(80px);
                 background: conic-gradient(from 0deg, transparent 0deg, rgba(255,90,121,.42) 60deg,
                   rgba(255,181,71,.16) 120deg, transparent 170deg, rgba(34,211,238,.36) 240deg,
                   rgba(167,139,250,.24) 300deg, transparent 360deg); }}
.hero::after {{ content: ""; position: absolute; inset: 0; z-index: -1;
                background: radial-gradient(rgba(255,255,255,.035) 1px, transparent 1.4px) 0 0 / 16px 16px;
                -webkit-mask-image: linear-gradient(180deg, #000, transparent 75%);
                mask-image: linear-gradient(180deg, #000, transparent 75%); }}
.hero-grade {{ display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 2.6rem;
               align-items: center; }}
.kicker {{ display: inline-flex; align-items: center; gap: .55rem; color: var(--ambar); font-size: .76rem;
           font-weight: 800; letter-spacing: .16em; text-transform: uppercase; background: rgba(221,176,108,.07);
           border: 1px solid rgba(221,176,108,.26); border-radius: 99px; padding: .38rem .85rem; }}
.kicker::before {{ content: ""; width: .5rem; height: .5rem; border-radius: 50%; background: var(--ambar); }}
.big {{ display: flex; align-items: flex-start; margin: 1rem 0 .3rem; font-size: clamp(6.2rem, 13.5vw, 12.5rem);
        font-weight: 900; font-stretch: 62%; line-height: .8; letter-spacing: -.03em; color: transparent;
        background: linear-gradient(180deg, #F1DCE0 0%, #E5A3AE 45%, #CF7483 100%);
        -webkit-background-clip: text; background-clip: text;
        animation: subir .9s var(--curva) both .15s; }}
.big .un {{ font-size: .3em; font-stretch: 80%; letter-spacing: 0; margin: .3em 0 0 .12em; }}
.big-sub {{ color: var(--texto); font-size: 1.6rem; font-weight: 800; font-stretch: 85%; line-height: 1.22;
            max-width: 31rem; animation: subir .9s var(--curva) both .3s; }}
.big-sub em {{ font-style: normal; color: var(--coral); }}
.comp {{ margin-top: 1.5rem; max-width: 36rem; animation: subir .9s var(--curva) both .45s; }}
.comp-topo {{ display: flex; justify-content: space-between; align-items: baseline; color: var(--suave);
              font-size: .78rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase;
              margin-bottom: .45rem; }}
.comp-topo b {{ color: var(--texto); font-size: 1.45rem; letter-spacing: 0; font-stretch: 75%; }}
.trilha {{ display: flex; height: 3.2rem; border-radius: 14px; overflow: hidden; background: rgba(255,255,255,.06);
           font-size: 1.25rem; font-weight: 900; font-stretch: 75%; }}
.trilha .reg {{ width: var(--w); display: flex; align-items: center; padding: 0 1rem; color: #03141B;
                background: linear-gradient(90deg, #4A8E9D, var(--ciano)); transform-origin: left;
                animation: crescer 1.1s var(--curva) both .6s; white-space: nowrap; }}
.trilha .ext {{ flex: 1; display: flex; align-items: center; justify-content: flex-end; padding: 0 1rem;
                color: #2B0510; white-space: nowrap; animation: surgir .6s ease both 1.5s;
                background: var(--coral); }}
.comp-leg {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: .3rem 1rem; color: var(--suave);
             font-size: .85rem; margin-top: .5rem; }}
.comp-leg i {{ display: inline-block; width: .7rem; height: .7rem; border-radius: 3px; margin-right: .4rem;
               vertical-align: -1px; }}
.frase {{ color: var(--suave); font-size: 1.04rem; line-height: 1.55; margin: 1.1rem 0 0; max-width: 36rem; }}
.frase b {{ color: var(--texto); }}

/* ruas animadas */
.ilustra {{ display: grid; gap: .55rem; padding: 1.2rem 1.25rem 1rem; border-radius: 24px;
            background: rgba(3,5,12,.6); border: 1px solid rgba(255,255,255,.09);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.06); animation: subir .9s var(--curva) both .35s; }}
.pista-rot {{ display: flex; justify-content: space-between; font-size: .74rem; font-weight: 800;
              letter-spacing: .15em; text-transform: uppercase; margin-top: .35rem; }}
.pista-rot span {{ color: var(--apagado); letter-spacing: .08em; }}
.pista {{ position: relative; height: 46px; border-radius: 12px; overflow: hidden;
          background: linear-gradient(180deg, #0D1226, #080B18); border: 1px solid rgba(255,255,255,.06); }}
.pista::before {{ content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 2px; margin-top: -1px;
                  background: repeating-linear-gradient(90deg, rgba(255,255,255,.16) 0 16px, transparent 16px 32px); }}
.pista::after {{ content: ""; position: absolute; left: 62%; top: 0; bottom: 0; width: 3px; z-index: 0;
                 background: var(--ambar); opacity: .8; }}
.trilho {{ position: absolute; inset: 0 auto 0 0; width: 200%; z-index: 1; animation: andar 15s linear infinite; }}
.bus {{ position: absolute; top: 50%; width: 38px; height: 19px; margin: -11px 0 0 -19px; border-radius: 5px 9px 9px 5px;
        background: var(--b); }}
.bus::before {{ content: ""; position: absolute; left: 4px; right: 8px; top: 4px; height: 6px; border-radius: 2px;
                background: repeating-linear-gradient(90deg, rgba(5,7,16,.72) 0 6px, transparent 6px 8px); }}
.bus::after {{ content: ""; position: absolute; left: 6px; bottom: -3px; width: 7px; height: 7px; border-radius: 50%;
               background: #C9D0EE; box-shadow: 19px 0 0 #C9D0EE; }}
.ilustra-pe {{ color: var(--suave); font-size: .86rem; line-height: 1.45; margin-top: .45rem; }}
.ilustra-pe i {{ display: inline-block; width: 3px; height: .9rem; background: var(--ambar); margin-right: .45rem;
                 vertical-align: -2px; }}
.tiles {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; margin-top: .9rem;
          animation: subir .9s var(--curva) both .55s; }}
.tile {{ border-radius: 18px; padding: .8rem .95rem .75rem; border: 1px solid color-mix(in srgb, var(--c) 24%, transparent);
         background: linear-gradient(160deg, color-mix(in srgb, var(--c) 9%, transparent), rgba(4,6,14,.6) 72%); }}
.tile .r {{ color: var(--suave); font-size: .68rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
.tile .v {{ color: var(--c); font-size: 2.3rem; font-weight: 900; font-stretch: 62%; line-height: 1.05;
            font-variant-numeric: tabular-nums; }}
.tile .v small {{ font-size: .5em; font-stretch: 85%; margin-left: .12em; }}
.hero-pe {{ margin-top: 1.7rem; padding-top: .9rem; border-top: 1px solid rgba(255,255,255,.08);
            color: var(--apagado); font-size: .86rem; }}

/* letreiro rolante */
.rolante {{ display: flex; align-items: stretch; margin: 1.4rem 0 .2rem; background: #030409; overflow: hidden;
            border: 1px solid #2A2410; border-radius: 16px;
            box-shadow: inset 0 0 0 4px #0A0B12; }}
.rolante .fixo {{ flex: none; display: flex; align-items: center; padding: .7rem 1.1rem; background: var(--ambar);
                  color: #030409; font-family: 'Doto', monospace; font-weight: 900; font-size: 1.1rem;
                  letter-spacing: .03em; text-transform: uppercase; }}
.rolante .janela {{ flex: 1; overflow: hidden;
                    -webkit-mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent);
                    mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent); }}
.rolante .vai {{ display: flex; width: max-content; animation: rolar 70s linear infinite; }}
.rolante .vai span {{ font-family: 'Doto', monospace; font-weight: 800; font-size: 1.45rem; color: var(--ambar);
                      white-space: nowrap; padding: .65rem 1.3rem; text-transform: uppercase; }}
.rolante .vai span em {{ font-style: normal; color: var(--apagado); }}
.rolante .vai span b {{ color: var(--coral); }}
.rolante:hover .vai {{ animation-play-state: paused; }}

/* paineis: cada um com a sua cor */
[class*="st-key-sec_"] {{ --acc: var(--ciano); position: relative; border-radius: 26px; margin-top: 1.4rem;
    padding: 1.6rem 1.8rem 1.3rem; border: 1px solid color-mix(in srgb, var(--acc) 15%, transparent);
    background: linear-gradient(165deg, color-mix(in srgb, var(--acc) 5%, rgba(16,22,52,.9)), rgba(7,10,24,.92) 55%);
    box-shadow: inset 0 1px 0 color-mix(in srgb, var(--acc) 28%, transparent), 0 30px 60px -45px rgba(0,0,0,.8);
    animation: subir .8s var(--curva) both; }}
.st-key-sec_faixa {{ --acc: var(--ciano); animation-delay: .5s; }}
.st-key-sec_tendencia {{ --acc: var(--coral); animation-delay: .6s; }}
.st-key-sec_linhas {{ --acc: var(--ambar); }}
.st-key-sec_mapa {{ --acc: var(--violeta); }}
.st-key-sec_colados {{ --acc: var(--coral); }}
.st-key-sec_ml {{ --acc: var(--menta); }}
.secao {{ display: flex; align-items: center; gap: 1.2rem; margin-bottom: .8rem; }}
.secao .num {{ flex: none; font-size: 5.4rem; font-weight: 900; font-stretch: 62%; line-height: .8;
               letter-spacing: -.03em; color: transparent; -webkit-text-stroke: 1.5px var(--acc); opacity: .85; }}
.secao .olho {{ color: var(--acc); font-size: .78rem; font-weight: 800; letter-spacing: .2em; }}
.secao .titulo {{ color: var(--texto); font-size: 2.1rem; font-weight: 900; font-stretch: 78%; line-height: 1.08;
                  letter-spacing: -.01em; margin-top: .1rem; }}
.secao .nota {{ color: var(--suave); font-size: .95rem; margin-top: .35rem; }}
.nota {{ color: var(--suave); font-size: .95rem; margin: .2rem 0 .8rem; }}

/* ranking de linhas */
.rank {{ display: grid; gap: .5rem; margin: .4rem 0 .9rem; }}
.rank .item {{ display: grid; grid-template-columns: 2rem 5rem minmax(0, 1fr) 5.6rem; gap: .8rem; align-items: center; }}
.rank .pos {{ color: var(--apagado); font-size: 1.5rem; font-weight: 900; font-stretch: 62%; text-align: right; }}
.rank .lin {{ font-family: 'Doto', monospace; font-weight: 900; font-size: 1.15rem; color: var(--ambar);
              background: #030409; border: 1px solid #2A2410; border-radius: 9px; text-align: center;
              padding: .3rem .2rem; }}
.rank .barra {{ position: relative; height: 2.4rem; border-radius: 11px; overflow: hidden;
                background: rgba(255,255,255,.045); }}
.rank .barra i {{ position: absolute; inset: 0 auto 0 0; width: var(--w); border-radius: 11px; transform-origin: left;
                  background: linear-gradient(90deg, color-mix(in srgb, var(--coral) 22%, transparent), color-mix(in srgb, var(--coral) 75%, transparent));
                  animation: crescer 1s var(--curva) both; animation-delay: calc(var(--i) * 70ms); }}
.rank .barra span {{ position: relative; display: block; padding: 0 .85rem; line-height: 2.4rem; color: var(--texto);
                     font-size: .92rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.rank .val {{ text-align: right; color: var(--texto); font-size: 1.5rem; font-weight: 900; font-stretch: 68%;
              line-height: 1; font-variant-numeric: tabular-nums; }}
.rank .val small {{ display: block; color: var(--coral); font-size: .78rem; font-weight: 700; font-stretch: 100%;
                    margin-top: .2rem; }}

/* legenda do mapa */
.legenda {{ display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .7rem; color: var(--suave);
            font-size: .88rem; margin: .7rem 0 .4rem; font-variant-numeric: tabular-nums; }}
.legenda i {{ width: 180px; height: 10px; border-radius: 99px;
              background: linear-gradient(90deg, {CIANO}, {DOURADO}, {CORAL}); }}
.legenda em {{ font-style: normal; color: var(--apagado); }}

/* cards */
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: .9rem; margin: .3rem 0 .8rem; }}
.card {{ border-radius: 20px; padding: 1.05rem 1.2rem 1rem; border: 1px solid color-mix(in srgb, var(--c) 24%, transparent);
         background: linear-gradient(160deg, color-mix(in srgb, var(--c) 9%, transparent), rgba(4,6,14,.55) 68%); }}
.card .rotulo {{ color: var(--suave); font-size: .76rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
.card .valor {{ color: var(--c); font-size: 3.4rem; font-weight: 900; line-height: 1.02; font-stretch: 62%;
                font-variant-numeric: tabular-nums; margin: .25rem 0 .2rem; }}
.card .valor small {{ font-size: .45em; font-weight: 800; font-stretch: 85%; margin-left: .12em; }}
.card .sub {{ color: var(--suave); font-size: .88rem; line-height: 1.35; }}
[data-testid="stCaptionContainer"] p {{ color: var(--apagado); }}
[data-testid="stExpander"] details {{ background: rgba(15,23,51,.55); border-radius: 16px; }}
.rodape {{ color: var(--apagado); font-size: .88rem; margin-top: 2rem; padding-top: 1rem;
           border-top: 1px dashed var(--borda); }}
.rodape a {{ color: var(--ciano); }}

@media (max-width: 900px) {{
  .hero-grade {{ grid-template-columns: minmax(0, 1fr); gap: 1.8rem; }}
}}
@media (max-width: 640px) {{
  .block-container {{ padding-top: 1.6rem; }}
  .letreiro .destino {{ font-size: 1.45rem; }} .letreiro .placa {{ font-size: 1.4rem; }}
  div:has(> .st-key-filtros) {{ position: static; padding-top: 0; margin-top: 0; background: none; }}
  .hero {{ padding: 1.6rem 1.1rem 1.1rem; border-radius: 24px; }}
  .big-sub {{ font-size: 1.3rem; }}
  .trilha {{ height: 2.8rem; font-size: 1.1rem; }}
  .ilustra {{ padding: 1rem .9rem .9rem; }}
  .bus {{ width: 26px; height: 14px; margin: -8px 0 0 -13px; }}
  .bus::before {{ left: 3px; right: 6px; top: 3px; height: 4px; }}
  .bus::after {{ left: 4px; width: 5px; height: 5px; box-shadow: 13px 0 0 #C9D0EE; }}
  .tile .v {{ font-size: 1.85rem; }} .tile {{ padding: .7rem .7rem .65rem; }}
  .rolante .fixo {{ font-size: .85rem; padding: .6rem .7rem; }} .rolante .vai span {{ font-size: 1.15rem; }}
  [class*="st-key-sec_"] {{ padding: 1.2rem .95rem 1rem; border-radius: 20px; }}
  .secao {{ gap: .8rem; }} .secao .num {{ font-size: 3.6rem; }} .secao .titulo {{ font-size: 1.5rem; }}
  .rank .item {{ grid-template-columns: 1.3rem 3.9rem minmax(0, 1fr) 4.4rem; gap: .5rem; }}
  .rank .lin {{ font-size: .95rem; }} .rank .barra span {{ font-size: .8rem; padding: 0 .5rem; }}
  .card .valor {{ font-size: 2.8rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; }} }}
</style>
"""


def card(rotulo: str, valor: str, sub: str, cor: str) -> str:
    num, _, unidade = valor.partition(" ")
    valor = f"{num}<small>{unidade}</small>" if unidade else num
    return (f'<div class="card" style="--c:{cor}"><div class="rotulo">{rotulo}</div>'
            f'<div class="valor">{valor}</div><div class="sub">{sub}</div></div>')


def cards(itens):
    st.markdown('<div class="cards">' + "".join(card(*i) for i in itens) + "</div>", unsafe_allow_html=True)


def tile(rotulo: str, valor: str, cor: str) -> str:
    num, _, unidade = valor.partition(" ")
    valor = f"{num}<small>{unidade}</small>" if unidade else num
    return f'<div class="tile" style="--c:{cor}"><div class="r">{rotulo}</div><div class="v">{valor}</div></div>'


def compacto(n: float) -> str:
    if n >= 1e6:
        return f"{br(n / 1e6)} mi"
    if n >= 1e3:
        return f"{br(n / 1e3, 0)} mil"
    return br(n, 0)


def titulo(olho: str, texto: str, nota: str = ""):
    num, _, nome = olho.partition(" · ")
    st.markdown(f'<div class="secao"><div class="num">{num}</div><div><div class="olho">{nome}</div>'
                f'<div class="titulo">{texto}</div>' + (f'<div class="nota">{nota}</div>' if nota else "")
                + "</div></div>", unsafe_allow_html=True)


# Os mesmos 7 onibus, na mesma velocidade: em grupos (hoje) e espacados (regulares).
# Posicoes em % da rua; a faixa anda uma rua inteira por volta e repete sem emenda.
EM_GRUPOS = [0, 9, 18, 27, 55, 64, 73]
IGUAIS = [100 / 7 * i for i in range(7)]


def _pista(posicoes: list, cor: str, rotulo: str, detalhe: str) -> str:
    onibus = "".join(f'<i class="bus" style="left:{x:.2f}%;--b:{cor}"></i>'
                     for p in posicoes for x in (p / 2, 50 + p / 2))
    return (f'<div class="pista-rot" style="color:{cor}">{rotulo}<span>{detalhe}</span></div>'
            f'<div class="pista"><div class="trilho">{onibus}</div></div>')


def ilustracao() -> str:
    return ('<div class="ilustra" role="img" aria-label="Animação: os mesmos sete ônibus passando em grupos, '
            'como hoje, e espaçados por igual">'
            + _pista(EM_GRUPOS, CORAL, "Hoje: em grupos", "7 ônibus")
            + _pista(IGUAIS, CIANO, "Intervalos iguais", "7 ônibus")
            + '<div class="ilustra-pe"><i></i>o ponto. Mesmos ônibus, mesma velocidade. Em grupos, abre-se um buraco '
              'longo, e quem chega nele espera mais.</div></div>')


def estilo(fig: go.Figure, altura: int = 380) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Archivo, Segoe UI, sans-serif", color=SUAVE, size=14), separators=",.",
                      margin=dict(l=8, r=8, t=44, b=8), height=altura,
                      hoverlabel=dict(font_size=14, font_family="Archivo, sans-serif", bgcolor="#0F1733",
                                      bordercolor=BORDA_FORTE),
                      legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0, font=dict(color=TEXTO)))
    fig.update_xaxes(gridcolor=GRADE, zeroline=False, linecolor=GRADE)
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
    """Hero: o numero da espera extra, gigante, com a barra de comparacao e as ruas animadas."""
    onde, params = f["onde"], f["params"]
    rede = dados(sql_metricas([], onde), params)
    if rede.empty or pd.isna(rede.iloc[0]["headways"]):
        st.warning("Nenhum intervalo medido com esses filtros. Tente outro período ou tipo de dia.")
        return
    r = rede.iloc[0]
    reg, ext = r["regular_min"], r["excesso_min"]
    tot = reg + ext
    quem = ("nas linhas escolhidas" if f["linhas"] else
            {"alta": "numa linha de alta frequência", "baixa": "numa linha de baixa frequência",
             "todas": "numa linha qualquer"}[f["freq"]])
    linhas = (f"{len(f['linhas'])} linha{'s' if len(f['linhas']) > 1 else ''} escolhida"
              f"{'s' if len(f['linhas']) > 1 else ''}" if f["linhas"] else
              {"alta": "alta frequência", "baixa": "baixa frequência", "todas": "todas as linhas"}[f["freq"]])
    recorte = " · ".join([data_br(f["de"])[:5] + " a " + data_br(f["ate"])[:5],
                          "todos os dias" if f["dia"] == "todos" else TIPOS_DIA[f["dia"]].lower(), linhas])
    st.markdown(
        '<section class="hero"><div class="hero-grade"><div>'
        f'<span class="kicker">{recorte}</span>'
        f'<div class="big">+{br(ext)}<span class="un">min</span></div>'
        '<div class="big-sub">de espera <em>a mais</em> em cada ida ao ponto, só porque os ônibus não passam '
        'em intervalos iguais</div>'
        f'<div class="comp"><div class="comp-topo"><span>Espera média no ponto</span><b>{br(tot)} min</b></div>'
        f'<div class="trilha"><span class="reg" style="--w:{100 * reg / tot:.1f}%">{br(reg)}</span>'
        f'<span class="ext">+{br(ext)}</span></div>'
        f'<div class="comp-leg"><span><i style="background:{CIANO}"></i>com intervalos iguais</span>'
        f'<span><i style="background:{CORAL}"></i>custo da irregularidade, +{br(100 * ext / reg, 0)}%</span></div></div>'
        f'<p class="frase">{TIPOS_DIA_FRASE[f["dia"]].capitalize()}, quem chega ao ponto {quem} espera em média '
        f'<b>{br(tot)} minutos</b> pelo ônibus. Com os mesmos ônibus em intervalos iguais, seriam '
        f'<b>{br(reg)} minutos</b>.</p></div>'
        '<div>' + ilustracao() + '<div class="tiles">'
        + tile("Colados", pct(r["colados_pct"]), DOURADO)
        + tile("Intervalos", compacto(r["headways"]), VIOLETA)
        + tile("Horas medidas", compacto(r["horas"]), MENTA)
        + '</div></div></div>'
        f'<div class="hero-pe">{br(r["headways"], 0)} intervalos medidos em {br(r["horas"], 0)} horas de serviço, '
        f'de {data_br(f["de"])} a {data_br(f["ate"])}. Média ponderada pelo tempo de serviço coberto. '
        'Colado: intervalo menor que 1/4 do intervalo médio.</div></section>',
        unsafe_allow_html=True)


def q_rolante(f, nomes):
    """Letreiro rolante com as linhas que mais somam espera extra (mesma consulta do quadro 04)."""
    onde, params = filtro(f["de"], f["ate"], f["tipo_dia"], f["alta"])
    df = dados(sql_metricas(["route_id"], onde), params)
    if df.empty:
        return
    df = df.sort_values("volume_min_h", ascending=False).head(12)
    itens = "".join(f'<span><em>{i}º</em> {rid} <b>+{br(e)} min</b></span>'
                    for i, (rid, e) in enumerate(zip(df["route_id"], df["excesso_min"]), 1))
    st.markdown(f'<div class="rolante" title="As 12 linhas que mais somam espera extra no recorte, com a espera '
                f'extra por passageiro de cada uma"><div class="fixo">Mais espera</div><div class="janela">'
                f'<div class="vai">{itens}{itens}</div></div></div>', unsafe_allow_html=True)


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
    fig.update_layout(barmode="stack", bargap=.32)
    fig.update_traces(marker_cornerradius=6, selector=dict(type="bar"))
    fig.update_yaxes(title=None, rangemode="tozero")
    fig.update_xaxes(tickangle=0, tickfont=dict(size=12))
    grafico(estilo(fig, 400))


# Eventos conferidos em notícias (fontes em docs/analise.md, seção 9).
EVENTOS = {
    "2026-10-04": "Eleição, 1º turno: ônibus de graça e 4 mil viagens extras",
    "2026-10-05": "Chuva forte de manhã, quase 50 mm",
    "2026-10-13": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-14": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-15": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-16": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-20": "Itinerário novo da linha 5033",
    "2026-10-21": "Ato de campanha no Centro (15h às 17h) e obra muda o trânsito da Cristiano Machado",
    "2026-10-25": "Eleição, 2º turno, com 4 mil viagens extras; temporal à tarde derruba árvores e semáforos",
    "2026-10-26": "Depois do temporal: 45 mil imóveis sem luz de manhã e árvores caídas em vias",
}
# Mesmos ônibus e viagens, mas com horas sem posição: a espera extra das linhas S fica inflada.
FALHA_S = {d: "GPS das suplementares falhou em parte do dia" for d in
           ("2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-29")}


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
                    line=dict(color=CORAL, width=2.5), marker=dict(size=6), fill="tozeroy",
                    fillcolor="rgba(226,130,143,.10)", hovertemplate="%{y:.2f} min<extra></extra>")
    dia = df["data_bh"].astype(str).str[:10]
    sup = not f["linhas"] or any(str(r).startswith("S") for r in f["linhas"])
    for nome, notas, simbolo, cor in (("Evento na cidade", EVENTOS, "diamond", DOURADO),
                                      ("Falha de GPS nas suplementares", FALHA_S if sup else {}, "circle-open", SUAVE)):
        m = dia.isin(notas)
        if m.any():
            fig.add_scatter(x=df.loc[m, "data_bh"], y=df.loc[m, "excesso_min"], name=nome, mode="markers",
                            marker=dict(symbol=simbolo, size=11, color=cor, line=dict(width=2, color=cor)),
                            customdata=dia[m].map(notas), hovertemplate="%{customdata}<extra></extra>")
    fig.update_xaxes(tickformat="%d/%m", hoverformat="%a %d/%m")
    fig.update_yaxes(rangemode="tozero")
    fig.update_layout(hovermode="x unified")
    grafico(estilo(fig, 400))
    if dia.isin(EVENTOS).any() or (sup and dia.isin(FALHA_S).any()):
        st.caption("Passe o mouse no losango para ver o evento do dia, achado em notícias. O círculo vazado marca "
                   "dias em que o GPS das linhas suplementares (S) falhou: a espera delas parece maior do que foi.")


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
    barras = df.head(10 if not f["linhas"] else 15)
    maior = barras["parte"].max() or 1
    st.markdown('<div class="rank">' + "".join(
        f'<div class="item"><div class="pos">{p}</div><div class="lin">{rid}</div>'
        f'<div class="barra"><i style="--w:{100 * v / maior:.1f}%;--i:{k}"></i>'
        f'<span>{nomes.get(rid, "")}</span></div>'
        f'<div class="val">{pct(v)}<small>+{br(e)} min</small></div></div>'
        for k, (p, rid, v, e) in enumerate(zip(barras["posicao"], barras["route_id"], barras["parte"],
                                               barras["excesso_min"])))
        + '</div>', unsafe_allow_html=True)
    st.caption("Barra: parte da espera extra da rede. Abaixo dela, a espera extra por passageiro na linha.")
    tabela = pd.DataFrame({
        "Posição": df["posicao"], "Linha": df["route_id"], "Nome": df["route_id"].map(nomes).fillna(""),
        "Regular (min)": df["regular_min"], "Extra (min)": df["excesso_min"], "% da espera extra": df["parte"],
        "Colados": df["colados_pct"], "Corte sem colagem": df["reducao_pct"], "Horas de serviço": df["horas"],
    })
    fmt = {"Regular (min)": lambda v: br(v, 2), "Extra (min)": lambda v: br(v, 2),
           "% da espera extra": lambda v: pct(v), "Colados": lambda v: pct(v),
           "Corte sem colagem": lambda v: pct(v), "Horas de serviço": lambda v: br(v, 0)}
    with st.expander(f"Tabela com todas as colunas ({len(tabela)} linhas)"):
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
    lo, hi = df["excesso_min"].quantile(.05), df["excesso_min"].quantile(.95)
    st.markdown(f'<div class="legenda"><span>{br(lo, 1)} min</span><i></i><span>{br(hi, 1)} min</span>'
                f'<em>espera extra por passageiro · tamanho: horas de serviço · {br(len(df), 0)} pontos, {janela}</em>'
                '</div>', unsafe_allow_html=True)
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
    fig = go.Figure(go.Bar(x=x, y=h["parte"] * 100, marker_color=cor, width=.045, marker_cornerradius=3,
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

    st.markdown(f'<div class="topo"><div class="letreiro"><span class="placa">BH</span>'
                f'<span class="destino">Radar de ônibus</span></div><div class="dir"><span class="selo">{selo}</span>'
                f'<a class="git" href="{REPO}" target="_blank">Código e método ↗</a></div></div>',
                unsafe_allow_html=True)

    filtros = st.container(key="filtros")
    c1, c2, c3, c4 = filtros.columns([1.3, 1, 1, 2])
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
        escolha = filtros.date_input("Datas", key="datas", min_value=INICIO, max_value=ultimo, format="DD/MM/YYYY")
        de, ate = (escolha[0], escolha[-1]) if isinstance(escolha, (tuple, list)) and escolha else (INICIO, ultimo)
    else:
        de, ate = intervalo(periodo, ultimo)
    gravar_endereco(periodo, de, ate, dia, freq, linhas)

    tipo_dia = None if dia == "todos" else dia
    alta = FREQ_VALOR[freq]
    onde, params = filtro(de, ate, tipo_dia, alta, linhas)
    f = dict(de=de, ate=ate, dia=dia, freq=freq, tipo_dia=tipo_dia, alta=alta, linhas=linhas,
             onde=onde, params=params)

    with st.container(key="hero"):
        quadro(lambda: q_manchete(f, nomes))
    quadro(lambda: q_rolante(f, nomes))
    esq, dir_ = st.columns(2, gap="medium")
    with esq:
        painel("faixa", lambda: q_faixa(f))
    with dir_:
        painel("tendencia", lambda: q_tendencia(f))
    painel("linhas", lambda: q_linhas(f, nomes))
    painel("mapa", lambda: q_mapa(f))
    painel("colados", lambda: q_colados(f))
    painel("ml", q_ml)
    st.write("")

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
    st.markdown(f'<div class="rodape">Código e método: <a href="{REPO}">{REPO.removeprefix("https://")}</a>. '
                "Dados: GTFS e GTFS-Realtime da PBH. Projeto independente, sem vínculo com a Prefeitura.</div>",
                unsafe_allow_html=True)

    if st.session_state.banco_fora:
        with aviso.container():
            st.warning("O banco não respondeu. Ele dorme quando ninguém usa e leva até 1 minuto para acordar.")
            st.button("Tentar de novo", type="primary")


main()
