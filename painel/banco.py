"""Acesso ao banco de servico (Neon, esquema radar) com o usuario so leitura, e os quadros que caem sozinhos.

A URL vem de st.secrets["PAINEL_URL"] (Streamlit Cloud) ou do .env local. Nunca a NEON_URL, que escreve.
"""
import logging
import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st

from painel.visual import md

RAIZ = Path(__file__).resolve().parent.parent


class BancoFora(Exception):
    """O banco nao respondeu nesta rodada; os quadros seguintes desistem na hora."""


class SemDado(Exception):
    """O recorte escolhido nao tem dado para este quadro."""


def url_banco() -> str | None:
    try:
        if "PAINEL_URL" in st.secrets:
            return st.secrets["PAINEL_URL"]
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    return os.environ.get("PAINEL_URL")


@st.cache_data(ttl=3600, show_spinner=False, max_entries=160)
def consultar(sql: str, params: tuple) -> pd.DataFrame:
    """Uma conexao por pedido, aberta e fechada aqui. Cache de 1 h por (consulta, filtros), nunca por usuario."""
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
    except SemDado:
        md('<div class="vazio">Sem dado no recorte escolhido</div>')
    except Exception:
        logging.exception("quadro %s falhou", getattr(func, "__name__", "?"))
        st.warning("Este quadro não carregou agora. Os outros seguem valendo.")


def painel(chave: str, cor: str, func, num: str = "", olho: str = "", titulo: str = "", nota: str = ""):
    """Painel numerado (como os do Power BI): cabecalho com numero vazado na cor do painel e o quadro dentro."""
    from painel.visual import cabeca
    with st.container(key=f"pn_{chave}"):
        md(f"<style>.st-key-pn_{chave} {{ --acc: {cor}; }}</style>"
           + (cabeca(num, olho, titulo, nota) if num else ""))
        quadro(func)
