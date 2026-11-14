"""Painel publico do radar-onibus-bh (Streamlit), com as 11 paginas do relatorio Power BI.

Le o banco de servico (Neon, esquema radar) com o usuario so leitura. As contas sao as de
painel/consultas.py, as mesmas das medidas do Power BI e as que a conciliacao confere contra os CSVs
da analise. Rodar da raiz do repositorio:

    streamlit run painel/app.py

A URL do banco vem de st.secrets["PAINEL_URL"] (Streamlit Cloud) ou do .env local (PAINEL_URL=...).
Nunca a NEON_URL, que escreve.
"""
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from painel.banco import BancoFora, dados  # noqa: E402
from painel.consultas import SQL_CARGA, SQL_LINHAS, filtro  # noqa: E402
from painel.formato import data_br  # noqa: E402
from painel.paginas import INICIO, PAGINAS  # noqa: E402
from painel.visual import CSS, md  # noqa: E402

BH = ZoneInfo("America/Sao_Paulo")
ANALISE = (date(2026, 9, 15), date(2026, 11, 5))
REPO = "https://github.com/gustavohenriqq/radar-onibus-bh"

TIPOS_DIA = {"dia_util": "Dia útil", "sabado": "Sábado", "domingo_feriado": "Domingo e feriado", "todos": "Todos"}
FREQS = {"alta": "Alta (até 15 min)", "baixa": "Baixa", "todas": "Todas"}
FREQ_VALOR = {"alta": True, "baixa": False, "todas": None}
PERIODOS = {"28d": "Últimos 28 dias", "7d": "Últimos 7 dias", "tudo": "Tudo desde 15/09",
            "analise": "Janela da análise (15/09 a 05/11)", "datas": "Escolher datas"}


# ---------- filtros e pagina no endereco, para o link reproduzir a visao ----------

def ler_endereco():
    if st.session_state.get("_endereco_lido"):
        return
    q = st.query_params
    if q.get("pagina") in PAGINAS:
        st.session_state.pagina = q["pagina"]
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


def gravar_endereco(pagina, periodo, de, ate, dia, freq, linhas):
    q = {"pagina": pagina, "periodo": periodo, "dia": dia, "freq": freq}
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


# ---------- pagina ----------

def main():
    st.set_page_config(page_title="Radar de ônibus BH", page_icon="🚌", layout="wide",
                       initial_sidebar_state="auto")
    md(CSS)
    st.session_state.banco_fora = False  # cada rodada tenta o banco de novo uma vez
    aviso = st.empty()
    ler_endereco()
    if st.session_state.get("pagina") not in PAGINAS:
        st.session_state.pagina = "visao"
    st.session_state._ultima_pagina = st.session_state.pagina

    ultimo = datetime.now(BH).date() - timedelta(days=1)
    selo = "ATUALIZAÇÃO DIÁRIA"
    nomes = {}
    try:
        carga = dados(SQL_CARGA)
        if not carga.empty:
            c = carga.iloc[0]
            ultimo = c["ate"]
            selo = (f"DADOS ATÉ {data_br(c['ate'])} · CARGA "
                    f"{c['carregado_em'].astimezone(BH).strftime('%d/%m %H:%M')}")
        nomes = dict(dados(SQL_LINHAS).itertuples(index=False, name=None))
    except BancoFora:
        pass
    except Exception:  # cabecalho segue com a data pelo relogio
        logging.exception("carga ou linhas falhou")

    pagina = st.session_state.pagina
    _, _, olho, titulo, desenhar = PAGINAS[pagina]
    partes = titulo.split("*")
    titulo_html = "".join(f"<em>{p}</em>" if i % 2 else p for i, p in enumerate(partes))
    md(f'<div class="topo"><div class="letreiro"><span class="placa">BH</span><span class="destino">Radar de ônibus'
       f'</span></div><div class="pagtit"><div class="k">{olho}</div><div class="t">{titulo_html}</div></div>'
       f'<div class="dir"><span class="selo">{selo}</span><a class="git" href="{REPO}" target="_blank">'
       'Código e método ↗</a></div></div>')

    with st.sidebar:
        md('<div class="menu-tit">PÁGINAS</div>')
        st.radio("Página", list(PAGINAS), key="pagina", label_visibility="collapsed",
                 format_func=lambda k: f"{PAGINAS[k][1]}  {PAGINAS[k][0]}")
    barra = st.container(key="barra")
    c1, c2, c3, c4 = barra.columns([1.2, 1, 1, 2.2])
    periodo = c1.selectbox("Período", list(PERIODOS), format_func=PERIODOS.get, key="periodo")
    dia = c2.selectbox("Tipo de dia", list(TIPOS_DIA), format_func=TIPOS_DIA.get, key="dia")
    freq = c3.selectbox("Frequência", list(FREQS), format_func=FREQS.get, key="freq",
                        help="Alta: intervalo médio de até 15 minutos na linha, sentido, dia e faixa. "
                             "Só aí vale a conta da espera: com ônibus de meia em meia hora, "
                             "o passageiro sai de casa no horário.")
    opcoes = sorted(nomes, key=lambda r: (len(r), r)) if nomes else st.session_state.get("linhas_pedidas", [])
    if "linhas_pedidas" in st.session_state:
        st.session_state.linhas = [x for x in st.session_state.pop("linhas_pedidas") if x in opcoes]
    linhas = c4.multiselect("Linha", opcoes, key="linhas", placeholder="Rede inteira",
                            format_func=lambda r: f"{r} · {nomes.get(r, '')}".rstrip(" ·"))
    if periodo == "datas":
        d = st.session_state.get("datas")
        if isinstance(d, (tuple, list)) and d:  # datas da URL presas ao que o banco tem
            d = tuple(min(max(x, INICIO), ultimo) for x in d)
        if not d or d[0] > d[-1]:
            d = (max(INICIO, ultimo - timedelta(days=27)), ultimo)
        st.session_state.datas = d
        escolha = barra.date_input("Datas", key="datas", min_value=INICIO, max_value=ultimo, format="DD/MM/YYYY")
        de, ate = (escolha[0], escolha[-1]) if isinstance(escolha, (tuple, list)) and escolha else (INICIO, ultimo)
    else:
        de, ate = intervalo(periodo, ultimo)
    gravar_endereco(pagina, periodo, de, ate, dia, freq, linhas)

    tipo_dia = None if dia == "todos" else dia
    alta = FREQ_VALOR[freq]
    onde, params = filtro(de, ate, tipo_dia, alta, linhas)
    f = dict(de=de, ate=ate, dia=dia, freq=freq, tipo_dia=tipo_dia, alta=alta, linhas=linhas, nomes=nomes,
             ultimo=ultimo, onde=onde, params=params)

    st.write("")
    desenhar(f)

    st.write("")
    with st.expander("Como a conta é feita"):
        st.markdown(
            "Quem chega ao ponto sem olhar o horário cai, com mais probabilidade, num intervalo longo, porque "
            "intervalos longos ocupam mais tempo do relógio. Com intervalos H entre ônibus de uma linha num ponto, "
            "a espera média é E[H²] / (2 E[H]) = E[H]/2 + Var(H) / (2 E[H]). O primeiro termo é a espera com ônibus "
            "regulares; o segundo, a espera extra pela irregularidade. Colado: intervalo menor que 1/4 do intervalo "
            "médio daquela linha, naquele ponto, dia e faixa. Volume: espera extra vezes horas de serviço, o peso "
            "de uma linha ou ponto na espera da rede.\n\n"
            "Os intervalos saem das posições do feed GTFS-Realtime da Prefeitura de Belo Horizonte, coletadas por "
            "este projeto a cada 30 segundos desde 14/09/2026. O banco do painel guarda somas reagregáveis por "
            "linha, sentido, dia e faixa, então qualquer filtro dá a mesma conta da análise e do relatório Power BI. "
            f"Na janela da análise (15/09 a 05/11), os números deste painel batem com os da "
            f"[análise]({REPO}/blob/main/docs/analise.md).")
    md(f'<div class="rodape">Código e método: <a href="{REPO}">{REPO.removeprefix("https://")}</a>. '
       "Dados: GTFS e GTFS-Realtime da PBH. Projeto independente, sem vínculo com a Prefeitura.</div>")

    if st.session_state.banco_fora:
        with aviso.container():
            st.warning("O banco não respondeu. Ele dorme quando ninguém usa e leva até 1 minuto para acordar.")
            st.button("Tentar de novo", type="primary")


main()
