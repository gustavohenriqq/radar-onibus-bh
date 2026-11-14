"""As 11 paginas do painel web, na ordem e com os quadros do Power BI (powerbi/relatorio.py).

Todo numero sai das somas de radar.linha_dia_faixa (e das outras tabelas do esquema radar) com a conta de
painel/consultas.py: as mesmas formulas das medidas do Power BI, entao os dois mostram o mesmo numero.
"""
from datetime import date, timedelta
from math import ceil

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
from plotly.subplots import make_subplots

from painel.banco import SemDado, dados, painel, quadro
from painel.consultas import (SOMAS, SQL_ML_LINHAS, SQL_QUALIDADE, agrega, filtro, filtro_paradas, metricas,
                              sql_hist, sql_paradas_somas, sql_somas, total)
from painel.eventos import EVENTOS, FALHA_S
from painel.formato import br, data_br, pct
from painel.visual import (AMBAR, APAGADO, AZUL, FUNDO, SUAVE, TEXTO, VERDE, VERMELHO, azulejos,
                           barra, cor_escala, esc, escala_legenda, estilo, grafico, md, rgb, sparkline)

INICIO = date(2026, 9, 15)
HORAS_MIN_PARADA = 25  # na janela de 28 dias (o mesmo corte do Power BI)
TOP_CALOR = 30
FAIXAS = {"madrugada": ("Madrugada", "0h às 5h"), "inicio_manha": ("Início da manhã", "5h às 6h"),
          "pico_manha": ("Pico da manhã", "6h às 9h"), "entre_picos": ("Entre picos", "9h às 16h"),
          "pico_tarde": ("Pico da tarde", "16h às 20h"), "noite": ("Noite", "20h às 24h")}
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
TIPOS = {"dia_util": "Dia útil", "sabado": "Sábado", "domingo_feriado": "Domingo e feriado"}
REDE = "__rede__"
PADRAO = object()  # "use o filtro da tela"


# ---------------------------------------------------------------------------
# Dados: somas do recorte, reagregadas em pandas
# ---------------------------------------------------------------------------
def somas(chaves, f, linhas=True, tipo=True, alta=PADRAO, de=None, ate=None) -> pd.DataFrame:
    onde, params = filtro(de or f["de"], ate or f["ate"], f["tipo_dia"] if tipo else None,
                          f["alta"] if alta is PADRAO else alta, f["linhas"] if linhas else None)
    return dados(sql_somas(chaves, onde), params)


def rd(f) -> pd.DataFrame:
    """Linha x dia, rede inteira (sem o filtro de linha): base de quase tudo."""
    return somas(["route_id", "data_bh"], f, linhas=False)


def rf(f) -> pd.DataFrame:
    """Linha x faixa horaria, rede inteira."""
    return somas(["route_id", "ordem_faixa", "faixa_horaria"], f, linhas=False)


def sel(df: pd.DataFrame, f) -> pd.DataFrame:
    return df[df["route_id"].isin(f["linhas"])] if f["linhas"] else df


def por_rota(f) -> pd.DataFrame:
    """Metricas por linha na rede inteira, com nome, posicao pelo volume e parte da espera extra da rede."""
    r = agrega(rd(f), ["route_id"])
    r = r[r["n"] > 0].sort_values(["volume_min_h", "route_id"], ascending=[False, True]).reset_index(drop=True)
    r["posicao"] = np.arange(1, len(r) + 1)
    r["parte"] = r["volume_min_h"] / r["volume_min_h"].sum()
    r["nome"] = r["route_id"].map(f["nomes"]).fillna("")
    return r


def recorte_total(f):
    t = total(sel(rd(f), f))
    if t is None:
        raise SemDado
    return t


def linhas_80(r: pd.DataFrame) -> int:
    v = r.sort_values("volume_min_h", ascending=False)["volume_min_h"]
    antes = v.cumsum() - v
    return int((antes < 0.8 * v.sum()).sum())


def compacto(n: float) -> str:
    if n >= 1e6:
        return f"{br(n / 1e6)} mi"
    if n >= 1e3:
        return f"{br(n / 1e3, 0)} mil"
    return br(n, 0)


def faixa_rotulo(cod: str) -> tuple[str, str]:
    return FAIXAS.get(cod, (cod, ""))


def lista(colunas: str, cab: list[str], linhas: list[list[str]], colunas_cel: str | None = None,
          ocultar: tuple = ()) -> str:
    """Tabela leve em grade. ocultar: indices das colunas que somem no celular."""
    def celulas(itens, tag):
        return "".join(f'<div class="{"oc" if i in ocultar else ""}">{x}</div>' for i, x in enumerate(itens))
    estilo_ = f"--gc:{colunas};" + (f"--gcm:{colunas_cel};" if colunas_cel else "")
    corpo = "".join(f'<div class="lin">{celulas(l, "div")}</div>' for l in linhas)
    return f'<div class="lista" style="{estilo_}"><div class="cab">{celulas(cab, "div")}</div>{corpo}</div>'


# ---------------------------------------------------------------------------
# Peças repetidas: dia a dia com eventos, faixa horaria, ilustracao
# ---------------------------------------------------------------------------
EM_GRUPOS = [0, 9, 18, 27, 55, 64, 73]  # os mesmos 7 onibus, em grupos (hoje) e espacados
IGUAIS = [100 / 7 * i for i in range(7)]


def _pista(posicoes: list, cor: str, rotulo: str) -> str:
    onibus = "".join(f'<i class="bus" style="left:{x:.2f}%;--b:{cor}"></i>'
                     for p in posicoes for x in (p / 2, 50 + p / 2))
    return (f'<div class="pista-rot" style="color:{cor}">{rotulo}<span>7 ônibus</span></div>'
            f'<div class="pista"><div class="trilho">{onibus}</div></div>')


def eventos_do_periodo(datas: list[str]) -> list[tuple[int, str, str]]:
    """(numero, primeiro dia, evento) dos eventos que caem nas datas, numerados pela ordem do primeiro dia."""
    primeiros = {}
    for d in sorted(datas):
        e = EVENTOS.get(d)
        if e and e not in primeiros:
            primeiros[e] = d
    return [(i, d, e) for i, (e, d) in enumerate(sorted(primeiros.items(), key=lambda x: x[1]), 1)]


def grafico_dia(d: pd.DataFrame, media: float, sup: bool, altura: int = 380):
    """Barras da espera extra por dia; barra clara e numero nos dias com evento; tracejado azul: a media."""
    d = d.sort_values("data_bh")
    dias = [str(x)[:10] for x in d["data_bh"]]
    evs = eventos_do_periodo(dias)
    num = {e: i for i, _, e in evs}
    cores = [TEXTO if EVENTOS.get(x) else AMBAR for x in dias]
    dica = []
    for x, v in zip(dias, d["excesso_min"]):
        s = f"{x[8:10]}/{x[5:7]}: +{br(v, 2)} min"
        if EVENTOS.get(x):
            s += f"<br>{num[EVENTOS[x]]}. {EVENTOS[x]}"
        if sup and FALHA_S.get(x):
            s += f"<br>{FALHA_S[x]}"
        dica.append(s)
    topo = max(2, ceil(float(d["excesso_min"].max()) * 1.3))
    fig = go.Figure()
    fig.add_bar(x=d["data_bh"], y=d["excesso_min"], marker_color=cores, marker_cornerradius=3, customdata=dica,
                hovertemplate="%{customdata}<extra></extra>", name="Espera extra")
    fig.add_hline(y=media, line=dict(color=AZUL, dash="dash", width=2))
    fig.add_annotation(x=0, xref="paper", y=1.0, yref="paper", xanchor="left", yanchor="bottom", showarrow=False,
                       text=f"<b>- -</b>  média do período: {br(media, 2)} min", font=dict(color=AZUL, size=13))
    valor = dict(zip(dias, d["excesso_min"]))
    for i, dia, _ in evs:
        cy = topo * (0.9 if i % 2 else 0.78)
        fig.add_shape(type="line", x0=dia, x1=dia, y0=valor[dia], y1=cy, line=dict(color=TEXTO, width=1, dash="dot"),
                      opacity=.5)
        fig.add_scatter(x=[dia], y=[cy], mode="markers+text", text=[str(i)], marker=dict(size=22, color=TEXTO),
                        textfont=dict(color=FUNDO, size=12, family="Archivo"), hoverinfo="skip", showlegend=False)
    fig.update_xaxes(tickformat="%d/%m", showgrid=False)
    fig.update_yaxes(range=[0, topo], title=None)
    fig.update_layout(bargap=.25, showlegend=False)
    return estilo(fig, altura, legenda=False), evs


def lista_eventos(evs) -> str:
    if not evs:
        return '<div class="eventos"><div class="tt">EVENTOS NA CIDADE</div><div class="rod">Nenhum evento anotado no período</div></div>'
    itens = "".join(f'<div class="e"><i>{i}</i><b>{d[8:10]}/{d[5:7]}</b><span>{esc(e)}</span></div>' for i, d, e in evs)
    return f'<div class="eventos"><div class="tt">EVENTOS NA CIDADE</div>{itens}</div>'


def quadro_dia(d: pd.DataFrame, media: float, sup: bool, altura: int = 360):
    if d.empty:
        raise SemDado
    fig, evs = grafico_dia(d, media, sup, altura)
    a, b = st.columns([2.7, 1], gap="medium")
    with a:
        grafico(fig)
    with b:
        md(lista_eventos(evs))


def lista_faixa(t: pd.DataFrame) -> str:
    """Espera por faixa horaria: barra regular (azul) mais a extra (ambar); a extra em destaque a direita."""
    t = t.sort_values("ordem_faixa")
    topo = float((t["regular_min"] + t["excesso_min"]).max())
    linhas = []
    for _, x in t.iterrows():
        nome, horas = faixa_rotulo(x["faixa_horaria"])
        wr, wx = x["regular_min"] / topo * 100, x["excesso_min"] / topo * 100
        linhas.append([
            f'<div class="nome"><b>{nome}</b><small>{horas}</small></div>',
            f'<div class="empilha"><i style="width:{wr:.1f}%;background:{AZUL}"></i>'
            f'<i style="width:{wx:.1f}%;background:{AMBAR}"></i></div>',
            f'<div class="num" style="color:{AMBAR}">+{br(x["excesso_min"], 2)}'
            f'<div style="color:{SUAVE};font-size:.8rem;font-weight:500">de {br(x["regular_min"] + x["excesso_min"], 1)} min</div></div>'])
    return lista("8.6rem minmax(0,1fr) 5.2rem", ["Faixa", "Regular + extra", "Extra"], linhas,
                 "6.4rem minmax(0,1fr) 4.6rem")


def faixas_do_recorte(f, linhas: list | None = None) -> pd.DataFrame:
    df = rf(f)
    alvo = f["linhas"] if linhas is None else linhas
    if alvo:
        df = df[df["route_id"].isin(alvo)]
    if df.empty:
        raise SemDado
    return agrega(df, ["ordem_faixa", "faixa_horaria"])


def tem_suplementar(linhas) -> bool:
    return not linhas or any(str(r).startswith("S") for r in linhas)


# ---------------------------------------------------------------------------
# 1. Visao geral
# ---------------------------------------------------------------------------
def recorte_texto(f) -> str:
    tipo = "todos os dias" if f["dia"] == "todos" else TIPOS[f["dia"]].lower()
    freq = {"alta": "alta frequência", "baixa": "baixa frequência", "todas": "todas as frequências"}[f["freq"]]
    n = len(f["linhas"])
    linhas = f"{n} linha escolhida" if n == 1 else (f"{n} linhas escolhidas" if n else "rede inteira")
    return f'{data_br(f["de"])[:5]} a {data_br(f["ate"])[:5]}  ·  {tipo}  ·  {freq}  ·  {linhas}'.upper()


def variacao(f, extra: float) -> tuple[str, str]:
    n = (f["ate"] - f["de"]).days + 1
    ini = f["de"] - timedelta(days=n)
    if ini < INICIO:
        return "Sem período anterior completo para comparar", SUAVE
    ant = total(somas([], f, de=ini, ate=f["de"] - timedelta(days=1)))
    if ant is None:
        return "Sem período anterior completo para comparar", SUAVE
    d = extra - ant["excesso_min"]
    seta = "▲ +" if d > 0 else "▼ −"
    return f"{seta}{br(abs(d), 2)} min contra os {n} dias anteriores", (VERMELHO if d > 0 else VERDE if d < 0 else SUAVE)


def q_capa(f):
    t = recorte_total(f)
    ee, er = t["excesso_min"], t["regular_min"]
    em = ee + er
    txt, cor = variacao(f, ee)
    md('<div class="capa"><div>'
       '<div class="r">ESPERA EXTRA POR IDA AO PONTO</div>'
       f'<div class="rec">{recorte_texto(f)}</div>'
       f'<div class="big">+{br(ee, 2)}<small>min</small></div>'
       '<div class="f1">de espera <em>a mais</em> em cada ida ao ponto,</div>'
       '<div class="f2">só porque os ônibus não passam em intervalos iguais</div>'
       f'<div class="pilula" style="--p:{cor}">{txt}</div></div>'
       '<div role="img" aria-label="Animação: os mesmos sete ônibus em grupos, como hoje, e espaçados por igual">'
       '<div class="dois">OS MESMOS ÔNIBUS, DE DOIS JEITOS</div>'
       + _pista(EM_GRUPOS, AMBAR, "HOJE: EM GRUPOS") + _pista(IGUAIS, AZUL, "INTERVALOS IGUAIS")
       + '<div class="ponto">a faixa clara é o ponto: em grupos, abre-se um buraco longo, e quem chega nele espera mais</div>'
       f'<div class="media"><div class="t">ESPERA MÉDIA NO PONTO: {br(em, 1)} MIN</div><div class="empilha">'
       f'<i style="width:{er / em * 100:.1f}%;background:{AZUL}">{br(er, 1)} regular</i>'
       f'<i style="width:{ee / em * 100:.1f}%;background:{AMBAR};justify-content:center">+{br(ee, 1)}</i></div></div>'
       '</div></div>'
       f'<div class="rod">{br(t["headways"], 0)} intervalos medidos em {br(t["horas"], 0)} horas de serviço, de '
       f'{data_br(f["de"])} a {data_br(f["ate"])}. Média ponderada pelo tempo de serviço coberto.</div>')


def q_numeros(f):
    t = recorte_total(f)
    n = sel(rd(f), f)
    n_linhas = n.loc[n["n"] > 0, "route_id"].nunique()
    md(azulejos([("Intervalos colados", pct(t["colados_pct"]), "menos de 1/4 do intervalo médio", VERMELHO),
                 ("Corte sem colagem", pct(t["reducao_pct"], 0), "da espera extra sumiria", VERDE),
                 ("Intervalos medidos", compacto(t["headways"]), "entre ônibus da mesma linha", AZUL),
                 ("Linhas medidas", br(n_linhas, 0), "com intervalo no recorte", TEXTO)]))


def q_rolante(f):
    r = por_rota(f).head(12)
    if r.empty:
        return
    itens = "".join(f'<span><em>{p}º</em> {esc(rid)} <b>+{br(e)} min</b></span>'
                    for p, rid, e in zip(r["posicao"], r["route_id"], r["excesso_min"]))
    md(f'<div class="rolante" title="As 12 linhas que mais somam espera extra no recorte, com a espera extra por '
       f'passageiro de cada uma"><div class="fixo">Mais espera</div><div class="janela"><div class="vai">{itens}{itens}'
       '</div></div></div>')


def q_dia_visao(f):
    d = agrega(sel(rd(f), f), ["data_bh"])
    t = recorte_total(f)
    quadro_dia(d, t["excesso_min"], tem_suplementar(f["linhas"]))


def pg_visao(f):
    a, b = st.columns([1.72, 1], gap="medium")
    with a:
        painel("v_capa", AMBAR, lambda: q_capa(f))
    with b:
        painel("v_num", AZUL, lambda: q_numeros(f), "02", "NÚMEROS DO RECORTE", "O tamanho da medição")
    quadro(lambda: q_rolante(f))
    a, b = st.columns([1.72, 1], gap="medium")
    with a:
        painel("v_dia", AMBAR, lambda: q_dia_visao(f), "03", "DIA A DIA", "Espera extra por dia",
               "Minutos a mais por ida ao ponto · barra clara: dia com evento na cidade, numerado na lista")
    with b:
        painel("v_faixa", AZUL, lambda: md(lista_faixa(faixas_do_recorte(f))), "04", "HORA DO DIA",
               "Espera por faixa horária", "Azul: com intervalos iguais · âmbar: a espera extra")


# ---------------------------------------------------------------------------
# 2. Onde e quando: mapas de calor
# ---------------------------------------------------------------------------
def celula(v, extra: str = "", grande: bool = False, dica: str = "") -> str:
    if v is None or v != v:
        return '<div class="c"></div>'
    fundo, letra = cor_escala(v)
    t = f' title="{esc(dica)}"' if dica else ""
    return (f'<div class="c{" g" if grande else ""}" style="background:{fundo};color:{letra}"{t}>{extra}'
            f'{br(v, 1)}</div>')


def cabecalho_faixas() -> str:
    return "".join(f'<div class="h">{n}<small>{h}</small></div>' for n, h in FAIXAS.values())


def q_calor(f):
    df = sel(rf(f), f)
    if df.empty:
        raise SemDado
    r = agrega(df, ["route_id"])
    top = r.sort_values(["volume_min_h", "route_id"], ascending=[False, True]).head(TOP_CALOR)
    top = top.sort_values("excesso_min", ascending=False)
    cel = agrega(df[df["route_id"].isin(top["route_id"])], ["route_id", "faixa_horaria"])
    v = {(a, b): x for a, b, x in zip(cel["route_id"], cel["faixa_horaria"], cel["excesso_min"])}
    linhas = []
    for rid in top["route_id"]:
        nome = f["nomes"].get(rid, "")
        linhas.append(f'<div class="l" title="{esc(nome)}">{esc(rid)}</div>' + "".join(
            celula(v.get((rid, cod)), dica=f"{rid} · {FAIXAS[cod][0]}: +{br(v.get((rid, cod)), 2)} min")
            for cod in FAIXAS))
    md(f'<div class="calor" style="--gc:4.4rem repeat(6, minmax(0, 1fr))"><div class="h"></div>{cabecalho_faixas()}'
       + "".join(linhas) + "</div>" + escala_legenda())


def q_calendario(f):
    d = agrega(sel(rd(f), f), ["data_bh"])
    if d.empty:
        raise SemDado
    d["dt"] = pd.to_datetime(d["data_bh"])
    d["semana"] = d["dt"] - pd.to_timedelta(d["dt"].dt.weekday, unit="D")
    v = {x.date(): e for x, e in zip(d["dt"], d["excesso_min"])}
    partes = ['<div class="h" style="text-align:left">SEMANA</div>'] + [f'<div class="h">{x}</div>' for x in DIAS_SEMANA]
    for s in sorted(d["semana"].unique()):
        s = pd.Timestamp(s).date()
        partes.append(f'<div class="l s">{s.strftime("%d/%m")}</div>')
        for k in range(7):
            dia = s + timedelta(days=k)
            e = v.get(dia)
            if e is None:
                partes.append('<div class="c"></div>')
                continue
            ev = EVENTOS.get(dia.isoformat(), "")
            dica = f"{dia.strftime('%d/%m')}: +{br(e, 2)} min" + (f" · {ev}" if ev else "")
            extra = f'<span class="d">{dia.day:02d}</span>' + ('<span class="ev"></span>' if ev else "")
            partes.append(celula(e, extra, True, dica))
    md('<div class="calor" style="--gc:3.6rem repeat(7, minmax(0, 1fr))">' + "".join(partes) + "</div>"
       + escala_legenda(False).replace('</div>', '<span style="margin-left:1rem">● dia com evento na cidade '
                                       '(passe o mouse)</span></div>', 1))


def q_semana(f):
    df = somas(["dia_semana", "ordem_faixa", "faixa_horaria"], f)
    if df.empty:
        raise SemDado
    df = metricas(df)
    v = {(int(a), b): x for a, b, x in zip(df["dia_semana"], df["faixa_horaria"], df["excesso_min"])}
    partes = ['<div class="h"></div>', cabecalho_faixas()]
    for k, nome in enumerate(DIAS_SEMANA, 1):
        partes.append(f'<div class="l s">{nome}</div>')
        partes += [celula(v.get((k, cod)), dica=f"{nome} · {FAIXAS[cod][0]}: +{br(v.get((k, cod)), 2)} min")
                   for cod in FAIXAS]
    md('<div class="calor" style="--gc:3rem repeat(6, minmax(0, 1fr))">' + "".join(partes) + "</div>")


def pg_onde(f):
    a, b = st.columns([1.3, 1], gap="medium")
    with a:
        painel("o_calor", AMBAR, lambda: q_calor(f), "01", "LINHA × FAIXA", f"As {TOP_CALOR} linhas que mais pesam",
               "Espera extra (min) por faixa · as de maior volume no recorte, da maior espera extra para a menor")
    with b:
        painel("o_cal", AMBAR, lambda: q_calendario(f), "02", "CALENDÁRIO", "Espera extra dia a dia",
               "Ponto branco: dia com evento na cidade · passe o mouse para ver o motivo")
        st.write("")
        painel("o_sem", AMBAR, lambda: q_semana(f), "03", "SEMANA × FAIXA", "Dia da semana e hora")


# ---------------------------------------------------------------------------
# 3. Linhas: concentracao, quadrantes, ranking
# ---------------------------------------------------------------------------
def q_pareto(f):
    r = por_rota(f)
    if r.empty:
        raise SemDado
    n80 = linhas_80(r)
    m = min(len(r), n80 + 15)
    p = r.head(m)
    acum = r["volume_min_h"].cumsum().head(m) / r["volume_min_h"].sum() * 100
    a, b = st.columns([1, 3.3], gap="medium")
    with a:
        md(f'<div style="padding-top:1.4rem"><div style="color:{AMBAR};font-size:5.6rem;font-weight:700;'
           f'font-stretch:70%;line-height:.9">{n80}</div><div style="color:{TEXTO};font-size:1.25rem;font-weight:700;'
           f'margin-top:.4rem">linhas somam 80%</div><div style="color:{SUAVE}">da espera extra da rede</div>'
           f'<div class="rod">são {pct(n80 / len(r), 0)} das {len(r)} linhas medidas</div></div>')
    with b:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        cores = [AMBAR if k <= n80 else APAGADO for k in p["posicao"]]
        fig.add_bar(x=p["posicao"], y=p["parte"] * 100, marker_color=cores, name="parte da linha",
                    customdata=np.stack([p["route_id"], p["nome"]], axis=1),
                    hovertemplate="%{x}ª · %{customdata[0]} %{customdata[1]}<br>%{y:.2f}% da espera extra<extra></extra>",
                    secondary_y=False)
        fig.add_scatter(x=p["posicao"], y=acum, mode="lines", line=dict(color=TEXTO, width=2), name="soma acumulada",
                        hovertemplate="até a %{x}ª: %{y:.0f}%<extra></extra>", secondary_y=True)
        fig.add_vline(x=n80 + .5, line=dict(color=AMBAR, dash="dash", width=1.5))
        fig.add_annotation(x=n80 + .5, y=1, yref="paper", text="<b>até aqui, 80%</b>", showarrow=False,
                           xanchor="right", font=dict(color=AMBAR, size=12))
        fig.update_layout(bargap=.15)
        fig.update_yaxes(ticksuffix="%", secondary_y=False, title=None)
        fig.update_yaxes(range=[0, 101], ticksuffix="%", secondary_y=True, showgrid=False, tickvals=[0, 50, 80, 100])
        fig.update_xaxes(title="linhas na ordem do volume de espera extra", ticksuffix="ª")
        grafico(estilo(fig, 300))


QUAD = [("muito colado e muita espera", VERMELHO), ("espera alta, pouco colado", AMBAR),
        ("muito colado, espera baixa", AZUL), ("abaixo da rede nas duas", APAGADO)]


def q_quadrantes(f):
    r = por_rota(f)
    rede = total(rd(f))
    if f["linhas"]:
        r = r[r["route_id"].isin(f["linhas"])]
    r = r.dropna(subset=["excesso_min", "colados_pct"])
    if r.empty or rede is None:
        raise SemDado
    rx, ry = rede["colados_pct"], rede["excesso_min"]
    q = np.where((r["colados_pct"] >= rx) & (r["excesso_min"] >= ry), 0,
                 np.where(r["excesso_min"] >= ry, 1, np.where(r["colados_pct"] >= rx, 2, 3)))
    hmax = r["horas"].max()
    fig = go.Figure()
    destaque = set(r.head(6)["route_id"])
    for k, (nome, cor) in enumerate(QUAD):
        s = r[q == k]
        if s.empty:
            continue
        fig.add_scatter(x=s["colados_pct"], y=s["excesso_min"], mode="markers+text", name=nome,
                        text=[x if x in destaque else "" for x in s["route_id"]], textposition="top right",
                        textfont=dict(color=TEXTO, size=12),
                        marker=dict(size=6 + 22 * np.sqrt(s["horas"] / hmax), color=cor, opacity=.75,
                                    line=dict(width=1, color=FUNDO)),
                        customdata=np.stack([s["route_id"], s["nome"], s["horas"]], axis=1),
                        hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>colados %{x:.1%} · extra +%{y:.2f} min"
                                      "<br>%{customdata[2]:,.0f} h de serviço<extra></extra>")
    mx = max(float(r["colados_pct"].quantile(.98)) * 1.15, rx * 1.6)
    my = max(float(r["excesso_min"].quantile(.98)) * 1.15, ry * 1.6)
    fig.add_vline(x=rx, line=dict(color=SUAVE, dash="dash", width=1))
    fig.add_hline(y=ry, line=dict(color=SUAVE, dash="dash", width=1))
    for (txt, cor), (x, y, xa, ya) in zip(QUAD, [(mx, my, "right", "top"), (0, my, "left", "top"),
                                                 (mx, 0, "right", "bottom"), (0, 0, "left", "bottom")]):
        fig.add_annotation(x=x, y=y, text=f"<b>{txt}</b>", showarrow=False, xanchor=xa, yanchor=ya,
                           font=dict(color=cor, size=12))
    fig.add_annotation(x=rx, y=ry, text=f"rede: {pct(rx)} · +{br(ry, 2)} min", showarrow=False, xanchor="left",
                       yanchor="bottom", xshift=4, font=dict(color=SUAVE, size=11))
    fig.update_xaxes(range=[0, mx], tickformat=".0%", title="intervalos colados")
    fig.update_yaxes(range=[0, my], title="espera extra (min)")
    grafico(estilo(fig, 420, legenda=False))


def series_por_linha(f, ids) -> dict:
    df = rd(f)
    datas = sorted(df["data_bh"].unique())
    m = metricas(df[df["route_id"].isin(ids)])
    out = {}
    for rid, g in m.groupby("route_id"):
        s = dict(zip(g["data_bh"], g["excesso_min"]))
        out[rid] = [s.get(d, np.nan) for d in datas]
    return out


def q_ranking(f):
    r = por_rota(f)
    if f["linhas"]:
        r = r[r["route_id"].isin(f["linhas"])]
    if r.empty:
        raise SemDado
    top = r.head(7)
    serie = series_por_linha(f, list(top["route_id"]))
    emax = float(top["excesso_min"].max())
    linhas = [[f'<span class="k">{p}ª</span>', f'<div class="lin2"><b>{esc(rid)}</b><span class="nome">{esc(nome)}</span></div>',
               sparkline(serie.get(rid, []), 160, 34),
               f'<span class="num">{pct(parte)}</span>', barra(e, emax, br(e, 2)),
               f'<span class="num" style="color:{VERMELHO}">{pct(c)}</span>']
              for p, rid, nome, parte, e, c in zip(top["posicao"], top["route_id"], top["nome"], top["parte"],
                                                   top["excesso_min"], top["colados_pct"])]
    md(lista("2rem minmax(0,1fr) 5.6rem 3.6rem 7rem 3.6rem",
             ["#", "Linha", "Dia a dia", "% rede", "Espera extra (min)", "Colados"], linhas,
             "2rem minmax(0,1fr) 7.5rem 3.6rem", ocultar=(2, 3)))
    tabela = pd.DataFrame({
        "Posição": r["posicao"], "Linha": r["route_id"], "Nome": r["nome"], "Regular (min)": r["regular_min"],
        "Extra (min)": r["excesso_min"], "% da espera extra": r["parte"], "Colados": r["colados_pct"],
        "Corte sem colagem": r["reducao_pct"], "Horas de serviço": r["horas"]})
    fmt = {"Regular (min)": lambda v: br(v, 2), "Extra (min)": lambda v: br(v, 2), "% da espera extra": pct,
           "Colados": pct, "Corte sem colagem": pct, "Horas de serviço": lambda v: br(v, 0)}
    with st.expander(f"Todas as linhas do recorte ({len(tabela)})"):
        st.dataframe(tabela.style.format(fmt), hide_index=True, width="stretch",
                     height=min(35 * (len(tabela) + 1) + 3, 640))


def pg_linhas(f):
    painel("l_pareto", AMBAR, lambda: q_pareto(f), "01", "CONCENTRAÇÃO", "Poucas linhas, muita espera",
           "Volume: espera extra × horas de serviço da linha · mede o peso dela na espera da rede")
    st.write("")
    a, b = st.columns([1, 1.05], gap="medium")
    with a:
        painel("l_quad", VERMELHO, lambda: q_quadrantes(f), "02", "QUADRANTES", "Colados contra espera extra",
               "Cada bolha é uma linha (tamanho: horas de serviço) · tracejado: a rede")
    with b:
        painel("l_rank", AMBAR, lambda: q_ranking(f), "03", "RANKING", "Onde está a espera extra",
               "As 7 de maior volume · para ver uma linha a fundo, abra a Ficha da linha")


# ---------------------------------------------------------------------------
# 4. Pontos (ultimos 28 dias)
# ---------------------------------------------------------------------------
def paradas(f) -> pd.DataFrame:
    onde, params = filtro_paradas(f["tipo_dia"], f["alta"])
    p = dados(sql_paradas_somas(onde), params)
    if p.empty:
        raise SemDado
    p["horas"] = p["soma"] / 3600
    p["excesso_min"] = p["dev2"] / 2 / p["soma"].replace(0, np.nan) / 60
    p["colados_pct"] = p["colados"] / p["n"].replace(0, np.nan)
    p["volume"] = p["dev2"] / 2 / 60 / 3600
    return p


def extra_de(p: pd.DataFrame) -> float:
    return float(p["dev2"].sum() / 2 / p["soma"].sum() / 60) if p["soma"].sum() else np.nan


def pontos_mapa(f) -> pd.DataFrame:
    p = paradas(f)
    m = p[p["horas"] >= HORAS_MIN_PARADA].dropna(subset=["lat", "lon", "excesso_min"])
    m = m.sort_values(["volume", "stop_id"], ascending=[False, True]).reset_index(drop=True)
    m["posicao"] = np.arange(1, len(m) + 1)
    m["parte"] = m["volume"] / m["volume"].sum()
    return m


def q_mapa(f):
    m = pontos_mapa(f)
    m["cor"] = [rgb(cor_escala(v)[0] if v >= 1.5 else "#3A4566", 215) for v in m["excesso_min"]]
    m["raio"] = 18 + 160 * np.sqrt(m["volume"] / m["volume"].max())
    m["txt"] = [f"{n}\nEspera extra: +{br(e, 2)} min\nColados: {pct(c)}\n{br(h, 0)} h de serviço · {int(l)} linhas"
                for n, e, c, h, l in zip(m["stop_name"], m["excesso_min"], m["colados_pct"], m["horas"],
                                         m["linhas"].fillna(0))]
    top = m.head(10).copy()
    top["rot"] = top["posicao"].astype(str)
    camadas = [
        pdk.Layer("ScatterplotLayer", m[["lon", "lat", "cor", "raio", "txt"]], get_position=["lon", "lat"],
                  get_fill_color="cor", get_radius="raio", radius_min_pixels=1.5, radius_max_pixels=16,
                  pickable=True, stroked=False),
        pdk.Layer("ScatterplotLayer", top[["lon", "lat", "txt"]], get_position=["lon", "lat"],
                  get_fill_color=rgb(TEXTO, 255), get_line_color=rgb(FUNDO, 255), line_width_min_pixels=1.5,
                  stroked=True, get_radius=60, radius_min_pixels=11, radius_max_pixels=11, pickable=True),
        pdk.Layer("TextLayer", top[["lon", "lat", "rot"]], get_position=["lon", "lat"], get_text="rot",
                  get_color=rgb(FUNDO, 255), get_size=13, font_weight=800, font_family="Archivo, sans-serif"),
    ]
    st.pydeck_chart(pdk.Deck(layers=camadas, initial_view_state=pdk.ViewState(latitude=-19.89, longitude=-43.95,
                                                                              zoom=10.6),
                             map_style="dark", tooltip={"text": "{txt}"}), height=620)
    md(escala_legenda() + '<div class="rod">tamanho: volume (espera extra × horas) · número: posição na tabela dos '
       'piores · cinza: menos de 1,5 min</div>')


def q_pnumeros(f):
    m = pontos_mapa(f)
    top10 = m["volume"].head(10).sum() / m["volume"].sum()
    janela = f'{data_br(m["janela_ini"].min())[:5]} a {data_br(m["janela_fim"].max())[:5]}'
    md(azulejos([(f"Com {HORAS_MIN_PARADA} h ou mais", br(len(m), 0), "pontos no mapa", TEXTO),
                 ("Espera extra média", f"+{br(extra_de(m), 2)} min", "nos pontos do mapa", AMBAR),
                 ("Os 10 piores somam", pct(top10), "da espera extra do mapa", VERMELHO),
                 ("Janela", "28 dias", janela.replace(" ", " "), SUAVE)], cols=4))


def q_piores(f):
    m = pontos_mapa(f).head(10)
    emax = float(m["excesso_min"].max())
    linhas = [[f'<span class="k">{p}</span>',
               f'<div class="nome"><b>{esc(n)}</b><small>{int(l) if l == l else "?"} linhas · {br(h, 0)} h</small></div>',
               barra(e, emax, f"+{br(e, 2)}"), f'<span class="num" style="color:{VERMELHO}">{pct(c)}</span>',
               f'<span class="num">{pct(pa)}</span>']
              for p, n, l, h, e, c, pa in zip(m["posicao"], m["stop_name"], m["linhas"], m["horas"], m["excesso_min"],
                                              m["colados_pct"], m["parte"])]
    md(lista("1.6rem minmax(0,1fr) 7.6rem 3.8rem 3.4rem", ["#", "Ponto", "Espera extra", "Colados", "Parte"],
             linhas, "1.4rem minmax(0,1fr) 7rem 3.6rem", ocultar=(3,)))


def pg_pontos(f):
    a, b = st.columns([1, 1.35], gap="medium")
    with a:
        painel("p_mapa", AMBAR, lambda: q_mapa(f), "01", "MAPA", "Espera extra por ponto",
               "Janela fixa dos últimos 28 dias: não segue o período nem a linha")
    with b:
        painel("p_num", AMBAR, lambda: q_pnumeros(f), "02", "OS PONTOS", "O que o mapa mostra")
        st.write("")
        painel("p_piores", AMBAR, lambda: q_piores(f), "03", "PIORES PONTOS", "Onde mais se espera a mais",
               "Ordem pelo volume (espera extra × horas de serviço no ponto) · o número é o mesmo do mapa")


# ---------------------------------------------------------------------------
# 5. Colados
# ---------------------------------------------------------------------------
def q_cnum(f):
    t = recorte_total(f)
    md(azulejos([("Intervalos colados", pct(t["colados_pct"]), "menos de 1/4 do intervalo médio", VERMELHO),
                 ("Abaixo de 60 segundos", pct(t["abaixo_60s_pct"]), "dos intervalos: praticamente juntos", VERMELHO),
                 ("Comboios", pct(t["comboio_pct"], 0), "dos colados são o 3º ônibus em diante", TEXTO),
                 ("Corte sem colagem", pct(t["reducao_pct"], 0), "da espera extra sumiria sem colagem", VERDE)], cols=4))


def q_hist(f):
    onde, params = filtro(f["de"], f["ate"], f["tipo_dia"], f["alta"])
    h = dados(sql_hist(onde), params)
    if h.empty:
        raise SemDado
    h["parte"] = h["headways"] / h["headways"].sum()
    x = [min(c, 80) * .05 + .025 for c in h["classe"]]
    cor = [VERMELHO if c < 5 else AZUL for c in h["classe"]]
    fig = go.Figure(go.Bar(x=x, y=h["parte"] * 100, marker_color=cor, width=.045, marker_cornerradius=2,
                           customdata=[("4 ou mais" if c >= 80 else f"{br(c * .05, 2)} a {br(c * .05 + .05, 2)}")
                                       for c in h["classe"]],
                           hovertemplate="intervalo de %{customdata} vezes o médio<br>%{y:.2f}% dos intervalos"
                                         "<extra></extra>"))
    for xv, txt, cor_ in ((.25, "COLADOS ←", VERMELHO), (1, "INTERVALO MÉDIO", TEXTO)):
        fig.add_vline(x=xv, line=dict(color=cor_, dash="dash", width=1.5))
        fig.add_annotation(x=xv, y=1, yref="paper", text=f"<b>{txt}</b>", showarrow=False,
                           xanchor="right" if xv < 1 else "left", font=dict(color=cor_, size=12))
    fig.update_xaxes(title="intervalo ÷ intervalo médio do grupo (1 = igual ao médio)",
                     range=[0, 4.05], dtick=.5)
    fig.update_yaxes(ticksuffix="%", title=None)
    grafico(estilo(fig, 470, legenda=False))


def q_cfaixa(f):
    t = faixas_do_recorte(f).sort_values("ordem_faixa")
    topo = float(t["colados_pct"].max())
    linhas = [[f'<div class="nome"><b>{faixa_rotulo(c)[0]}</b><small>{faixa_rotulo(c)[1]}</small></div>',
               barra(v, topo, pct(v), VERMELHO)] for c, v in zip(t["faixa_horaria"], t["colados_pct"])]
    md(lista("8.6rem minmax(0,1fr)", ["Faixa", "Intervalos colados"], linhas))


def q_clinhas(f):
    r = por_rota(f)
    if f["linhas"]:
        r = r[r["route_id"].isin(f["linhas"])]
    top = r.sort_values(["colados", "route_id"], ascending=[False, True]).head(5)
    if top.empty:
        raise SemDado
    topo = float(top["colados"].max())
    linhas = [[f'<div class="lin2"><b>{esc(rid)}</b><span class="nome">{esc(n)}</span></div>',
               barra(c, topo, compacto(c), VERMELHO), f'<span class="num">{pct(p)}</span>']
              for rid, n, c, p in zip(top["route_id"], top["nome"], top["colados"], top["colados_pct"])]
    md(lista("minmax(0,1fr) 7.8rem 3.8rem", ["Linha", "Colados", "% da linha"], linhas))


def pg_colados(f):
    painel("c_num", VERMELHO, lambda: q_cnum(f))
    st.write("")
    a, b = st.columns([1.35, 1], gap="medium")
    with a:
        painel("c_hist", VERMELHO, lambda: q_hist(f), "02", "DISTRIBUIÇÃO", "Como os intervalos se espalham",
               "Parte dos intervalos em cada tamanho · rede inteira: não segue o filtro de linha")
    with b:
        painel("c_faixa", VERMELHO, lambda: q_cfaixa(f), "03", "HORA DO DIA", "Colados por faixa horária")
        st.write("")
        painel("c_linhas", VERMELHO, lambda: q_clinhas(f), "04", "LINHAS", "Onde mais se cola",
               "Intervalos colados no recorte · % dos intervalos da linha")


# ---------------------------------------------------------------------------
# 6. Previsao (o teste da fase 5: nao segue periodo, tipo de dia nem frequencia)
# ---------------------------------------------------------------------------
def previsao(f) -> pd.DataFrame:
    p = dados(SQL_ML_LINHAS)
    if f["linhas"]:
        p = p[p["route_id"].isin(f["linhas"])]
    if p.empty or not p["alertas"].sum():
        raise SemDado
    return p


def q_pv_capa(f):
    p = previsao(f)
    t = p[["exemplos", "positivos", "alertas", "acertos"]].sum()
    ac, ch = t["acertos"] / t["alertas"], t["positivos"] / t["exemplos"]
    janela = (f'TESTE DE {data_br(p["data_bh"].min())[:5]} A {data_br(p["data_bh"].max())[:5]}  ·  LIMIAR '
              f'{br(p["limiar"].max(), 3)}')
    md(f'<div class="capa" style="--c:{VERDE}"><div><div class="r">ACERTO DOS ALERTAS</div>'
       f'<div class="rec">{janela}</div><div class="big">{br(ac * 100, 1)}<small>%</small></div>'
       '<div class="f1">dos ônibus com alerta <em>chegaram colados</em>,</div>'
       '<div class="f2">testado uma vez, em dias que o modelo não tinha visto</div>'
       f'<div class="pilula" style="--p:{VERDE}">Uso sugerido: lista de prioridade para o controle</div></div>'
       '<div><div class="dois">COM E SEM O MODELO</div><div class="comp">'
       f'<div class="q">Ônibus qualquer chega colado<b style="--c:{APAGADO}">{pct(ch)}</b></div>'
       f'<div class="t"><i style="--w:{ch / max(ac, ch) * 100:.1f}%;--c:{APAGADO}"></i></div>'
       f'<div class="q">Ônibus com alerta chega colado<b style="--c:{VERDE}">{pct(ac)}</b></div>'
       f'<div class="t"><i style="--w:{ac / max(ac, ch) * 100:.1f}%;--c:{VERDE}"></i></div></div>'
       f'<div class="r-val" style="margin-top:1rem"><b style="color:{VERDE}">{br(ac / ch, 1)}×</b>'
       '<span>a chance de um ônibus qualquer. O acerto passa dos 60% que um alerta precisa para se pagar, mas por '
       'pouco: o ganho estimado é de cerca de 1% do custo de nunca alertar.</span></div></div></div>')


def q_pv_num(f):
    t = previsao(f)[["exemplos", "positivos", "alertas", "acertos"]].sum()
    md(azulejos([("Alertas", br(t["alertas"], 0), "passagens apontadas pelo modelo", TEXTO),
                 ("Acertos", br(t["acertos"], 0), "chegaram colados de fato", VERDE),
                 ("Colados avisados", pct(t["acertos"] / t["positivos"], 0), "dos colados tiveram alerta", TEXTO),
                 ("Passagens no teste", compacto(t["exemplos"]), "ônibus avaliados pelo modelo", TEXTO)]))


def q_pv_dia(f):
    d = previsao(f).groupby("data_bh", as_index=False)[["alertas", "acertos"]].sum().sort_values("data_bh")
    d["acerto"] = d["acertos"] / d["alertas"].replace(0, np.nan)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=d["data_bh"], y=d["alertas"], name="alertas", marker_color="rgba(154,163,194,.45)",
                hovertemplate="%{y:,.0f} alertas<extra></extra>", secondary_y=False)
    fig.add_bar(x=d["data_bh"], y=d["acertos"], name="acertos", marker_color=VERDE,
                hovertemplate="%{y:,.0f} acertos<extra></extra>", secondary_y=False)
    fig.add_scatter(x=d["data_bh"], y=d["acerto"], name="acerto do dia", mode="lines+markers",
                    line=dict(color=TEXTO, width=2), hovertemplate="%{y:.0%} de acerto<extra></extra>", secondary_y=True)
    fig.update_layout(barmode="overlay", bargap=.3, hovermode="x unified")
    fig.update_xaxes(tickformat="%d/%m")
    fig.update_yaxes(secondary_y=False, title=None, separatethousands=True)
    fig.update_yaxes(secondary_y=True, tickformat=".0%", range=[0, 1], showgrid=False)
    grafico(estilo(fig, 380))


def q_pv_linhas(f):
    p = previsao(f).groupby("route_id", as_index=False)[["alertas", "acertos"]].sum()
    top = p.sort_values(["alertas", "route_id"], ascending=[False, True]).head(7)
    topo = float(top["alertas"].max())
    linhas = [[f'<div class="lin2"><b>{esc(rid)}</b><span class="nome">{esc(f["nomes"].get(rid, ""))}</span></div>',
               barra(a, topo, br(a, 0), AZUL),
               f'<span class="num" style="color:{VERDE}">{pct(c / a if a else None, 0)}</span>']
              for rid, a, c in zip(top["route_id"], top["alertas"], top["acertos"])]
    md(lista("minmax(0,1fr) 8.5rem 3.6rem", ["Linha", "Alertas", "Acerto"], linhas))


def pg_previsao(f):
    a, b = st.columns([1.72, 1], gap="medium")
    with a:
        painel("pv_capa", VERDE, lambda: q_pv_capa(f))
    with b:
        painel("pv_num", VERDE, lambda: q_pv_num(f), "02", "O TESTE", "Fora da amostra, uma vez")
    st.write("")
    a, b = st.columns([1.72, 1], gap="medium")
    with a:
        painel("pv_dia", VERDE, lambda: q_pv_dia(f), "03", "DIA A DIA", "Alertas e acertos no teste",
               "O teste foi feito uma vez: não segue período, tipo de dia nem frequência · segue o filtro de linha")
    with b:
        painel("pv_lin", VERDE, lambda: q_pv_linhas(f), "04", "LINHAS", "Onde o modelo mais avisou",
               "Alertas no teste e quantos chegaram colados")


# ---------------------------------------------------------------------------
# 7. Confianca: qualidade do dado
# ---------------------------------------------------------------------------
def qualidade(f) -> pd.DataFrame:
    q = dados(SQL_QUALIDADE)
    q = q[(q["data_bh"] >= f["de"]) & (q["data_bh"] <= f["ate"])]
    if q.empty:
        raise SemDado
    return q


def q_perguntas(f):
    q = qualidade(f)
    cob = q["headways_validos"].sum() / q["passagens"].sum()
    q = q.assign(c=q["headways_validos"] / q["passagens"])
    pior = q.sort_values(["c", "data_bh"]).iloc[0]
    t = recorte_total(f)
    feed = q["headways_feed_parado"].sum()
    dias_f = int((q["headways_feed_parado"] > 0).sum())
    quedas = f"nenhuma queda nos {len(q)} dias" if dias_f == 0 else f"queda em {dias_f} de {len(q)} dias"
    cards = [
        ("Os ônibus aparecem no dado?", pct(cob), TEXTO, "das passagens viram um intervalo válido",
         f"pior dia: {data_br(pior['data_bh'])[:5]}, com {pct(pior['c'])}",
         "✓ Sim: mais de 9 em cada 10" if cob >= .9 else "⚠ Abaixo de 90%: leia com cuidado",
         VERDE if cob >= .9 else AMBAR),
        ("A hora estimada distorce a conta?", f"{br(t['vies_min'] * 60, 1)} s", TEXTO,
         "a mais na espera extra, por erro de interpolação", f"é {pct(t['vies_pct'], 2)} da espera extra",
         "✓ Não: menos de 1% da espera extra" if t["vies_pct"] < .01 else "⚠ Mais de 1% da espera extra",
         VERDE if t["vies_pct"] < .01 else AMBAR),
        ("E quando o feed da PBH para?", compacto(feed), VERMELHO, "intervalos descartados, não estimados",
         f"{pct(feed / q['headways'].sum())} dos intervalos · {quedas}", "✓ Ficam fora da conta da espera", VERDE),
    ]
    md('<div class="perg">' + "".join(
        f'<div class="q" style="--c:{c}"><h4>{p}</h4><div class="v">{v}</div><p>{l1}</p><p>{l2}</p>'
        f'<div style="flex:1"></div><div class="vd" style="--p:{cv}">{vd}</div></div>'
        for p, v, c, l1, l2, vd, cv in cards) + "</div>")


def q_qdia(f):
    q = qualidade(f).sort_values("data_bh")
    q["c"] = q["headways_validos"] / q["passagens"]
    cob = q["headways_validos"].sum() / q["passagens"].sum()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.14, row_heights=[.62, .38],
                        subplot_titles=("<b>COBERTURA POR DIA</b>  intervalos válidos por passagem · eixo de 80% a 100%",
                                        "<b>INTERVALOS DESCARTADOS COM O FEED PARADO</b>  ficam fora da conta da espera"))
    fig.add_scatter(x=q["data_bh"], y=q["c"], mode="lines+markers", line=dict(color=AZUL, width=2.5),
                    marker=dict(size=6), name="cobertura", hovertemplate="%{y:.1%}<extra>cobertura</extra>",
                    row=1, col=1)
    fig.add_hline(y=cob, line=dict(color=AZUL, dash="dash", width=1), row=1, col=1)
    fig.add_bar(x=q["data_bh"], y=q["headways_feed_parado"], marker_color=VERMELHO, name="feed parado",
                hovertemplate="%{y:,.0f} intervalos<extra>feed parado</extra>", row=2, col=1)
    fig.update_yaxes(range=[.8, 1.0], tickformat=".0%", row=1, col=1)
    fig.update_yaxes(separatethousands=True, row=2, col=1)
    fig.update_xaxes(tickformat="%d/%m")
    for a, cor in zip(fig.layout.annotations, (AZUL, VERMELHO)):
        a.update(x=0, xanchor="left", font=dict(size=12, color=cor))
    grafico(estilo(fig, 470, legenda=False))
    md(f'<div class="rod">Média do período: <b>{pct(cob)}</b> de cobertura. Uma queda indica feed parado ou falha de '
       f'coleta naquele dia. {br(q["passagens"].sum(), 0)} passagens de ônibus por ponto reconstruídas.</div>')


def pg_qualidade(f):
    painel("q_perg", AZUL, lambda: q_perguntas(f))
    st.write("")
    painel("q_dia", AZUL, lambda: q_qdia(f), "02", "DIA A DIA", "Cobertura e quedas do feed",
           "Em cada dia do recorte: quanto do dado virou intervalo e quanto foi descartado com o feed parado")


# ---------------------------------------------------------------------------
# 8. Simulador
# ---------------------------------------------------------------------------
EXPLICA_SIMULADOR = ("Como a conta funciona: tira da espera extra a parte que some quando o ônibus atrasado, que "
                     "puxou o de trás, passa no meio do caminho entre os dois (o corte sem colagem). Não inclui o 3º "
                     "ônibus em diante de um comboio.")


def simulada(df: pd.DataFrame, e: float) -> pd.Series:
    return (df["dev2"] - e * df["reducao"]) / df["soma"].replace(0, np.nan) / 2 / 60


def q_controle(f):
    if st.session_state.get("espacamento") not in (0, .25, .5, .75, 1):
        st.session_state.espacamento = .5
    e = st.select_slider("Pares colados que o controle espaça", options=[0, .25, .5, .75, 1], key="espacamento",
                         format_func=lambda v: pct(v, 0))
    s = sel(rd(f), f)
    t = recorte_total(f)
    soma = s[SOMAS].sum()
    es = float((soma["dev2"] - e * soma["reducao"]) / soma["soma"] / 2 / 60)
    ee = t["excesso_min"]
    g = ee - es
    ws = es / ee * 100 if ee else 0
    md(f'<div style="color:{VERDE};font-weight:800;letter-spacing:.12em;font-size:.82rem;margin:.6rem 0 1rem">'
       f'ESPAÇANDO {pct(e, 0)} DOS PARES COLADOS</div>'
       f'<div class="dois">ESPERA EXTRA HOJE</div><div class="r-val"><b style="color:{AMBAR}">+{br(ee, 2)}</b>'
       '<span>min por ida ao ponto</span></div>'
       f'<div class="comp"><div class="t"><i style="--w:100%;--c:{AMBAR}"></i></div></div>'
       f'<div class="dois" style="margin-top:1rem">COM O ESPAÇAMENTO</div><div class="r-val"><b style="color:{VERDE}">'
       f'+{br(es, 2)}</b><span>min</span></div>'
       f'<div class="comp"><div class="t"><i style="--w:{ws:.1f}%;--c:{VERDE}"></i></div></div>'
       f'<div class="dois" style="margin-top:1.1rem">GANHO POR IDA AO PONTO</div>'
       f'<div class="r-val"><b style="color:{VERDE};font-size:3.4rem">−{br(g, 2)}</b><span>min</span></div>'
       f'<div style="color:{TEXTO};font-size:1.05rem">cerca de {br(g * 60, 0)} segundos a menos</div>'
       f'<div style="color:{SUAVE}">{pct(g / t["media_min"])} da espera média no ponto</div>'
       f'<div class="rod" style="margin-top:1rem">{EXPLICA_SIMULADOR}</div>')


def q_sfaixa(f):
    e = st.session_state.get("espacamento", .5)
    t = faixas_do_recorte(f).sort_values("ordem_faixa")
    t["sim"] = simulada(t, e)
    x = [f"{faixa_rotulo(c)[0]}<br>{faixa_rotulo(c)[1]}" for c in t["faixa_horaria"]]
    fig = go.Figure()
    fig.add_bar(x=x, y=t["excesso_min"], name="espera extra hoje", marker_color=AMBAR, marker_cornerradius=4,
                text=[f"+{br(v, 2)}" for v in t["excesso_min"]], textposition="outside",
                hovertemplate="%{y:.2f} min<extra>hoje</extra>")
    fig.add_bar(x=x, y=t["sim"], name=f"com {pct(e, 0)} dos pares espaçados", marker_color=VERDE,
                marker_cornerradius=4, text=[f"+{br(v, 2)}" for v in t["sim"]], textposition="outside",
                hovertemplate="%{y:.2f} min<extra>simulada</extra>")
    fig.update_traces(textfont=dict(color=TEXTO, size=12), cliponaxis=False)
    fig.update_layout(barmode="group", bargap=.28, bargroupgap=.08)
    fig.update_yaxes(title=None, rangemode="tozero")
    grafico(estilo(fig, 360))


def q_ganho(f):
    e = st.session_state.get("espacamento", .5)
    r = por_rota(f)
    r["poupado"] = e * r["reducao"] / 2 / 60 / 3600
    r["parte_ganho"] = r["poupado"] / r["poupado"].sum() if r["poupado"].sum() else np.nan
    r["ganho"] = r["excesso_min"] - simulada(r, e)
    if f["linhas"]:
        r = r[r["route_id"].isin(f["linhas"])]
    top = r.sort_values(["parte_ganho", "route_id"], ascending=[False, True]).head(7)
    if top.empty or not top["poupado"].sum():
        md('<div class="vazio">Com 0% dos pares espaçados não há ganho. Mova o controle à direita.</div>')
        return
    topo = float(top["ganho"].max())
    linhas = [[f'<div class="lin2"><b>{esc(rid)}</b><span class="nome">{esc(n)}</span></div>',
               f'<span class="num" style="color:{AMBAR}">+{br(x, 2)}</span>', barra(g, topo, f"−{br(g, 2)}", VERDE),
               f'<span class="num">{pct(p)}</span>']
              for rid, n, x, g, p in zip(top["route_id"], top["nome"], top["excesso_min"], top["ganho"],
                                         top["parte_ganho"])]
    md(lista("minmax(0,1fr) 4.2rem 8.5rem 4rem", ["Linha", "Hoje", "Ganho (min)", "Do ganho"], linhas,
             "minmax(0,1fr) 7.5rem 3.6rem", ocultar=(1,)))


def pg_simulador(f):
    a, b = st.columns([1, 2.1], gap="medium")
    with a:
        painel("s_ctl", VERDE, lambda: q_controle(f), "01", "E SE", "Espaçar os ônibus colados",
               "Quantos pares colados o controle consegue espaçar")
    with b:
        painel("s_faixa", VERDE, lambda: q_sfaixa(f), "02", "POR FAIXA", "Espera extra hoje e simulada")
        st.write("")
        painel("s_ganho", VERDE, lambda: q_ganho(f), "03", "ONDE MAIS GANHA", "Linhas com maior ganho",
               "Ordem pela parte do ganho da rede · é o tamanho do problema, não ganho garantido")


# ---------------------------------------------------------------------------
# 9. Ficha da linha
# ---------------------------------------------------------------------------
ORDENS = {"maior": "Maior espera", "menor": "Menor espera", "peso": "Peso na rede"}


def ordem_ficha(r: pd.DataFrame, ordem: str) -> list[str]:
    com = r.dropna(subset=["excesso_min"])
    sem = r[r["excesso_min"].isna()]
    if ordem == "peso":
        ids = list(com.sort_values("posicao")["route_id"])
    else:
        ids = list(com.sort_values(["excesso_min", "route_id"], ascending=[ordem == "menor", True])["route_id"])
    return [REDE] + ids + list(sem["route_id"])


def mover(ids: list, passo: int):
    atual = st.session_state.get("ficha", REDE)
    i = ids.index(atual) if atual in ids else 0
    st.session_state.ficha = ids[(i + passo) % len(ids)]


def cartao(rid: str, r: pd.DataFrame, rede, serie: dict, ordem: str, i: int, n: int, centro: bool,
           lado2: bool) -> str:
    if rid == REDE:
        x, nome, pos, cod = rede, "Toda a rede de ônibus", f"{len(r)} linhas medidas", "REDE"
    else:
        x = r.set_index("route_id").loc[rid]
        nome, pos, cod = x["nome"], f"{int(x['posicao'])}ª de {len(r)} no peso", rid
    classe = "cartao" + (" centro" if centro else "") + (" lado2" if lado2 else "")
    corpo = (f'<div class="{classe}"><span class="lin">{esc(cod)}</span><div class="nm">{esc(nome)}</div>'
             f'<div class="vv">+{br(x["excesso_min"], 2)}<small>min extra</small></div><div class="pos">{pos}</div>')
    if centro:
        corpo += (f'<div class="gr"><div>MÉDIA<b>{br(x["media_min"], 1)} min</b></div>'
                  f'<div>COLADOS<b>{pct(x["colados_pct"])}</b></div><div>CORTE<b>{pct(x["reducao_pct"], 0)}</b></div>'
                  f'<div>DA REDE<b>{pct(x["parte"], 1)}</b></div></div>'
                  + sparkline(serie.get(rid, []), 300, 52, ref=rede["excesso_min"] if rid != REDE else None)
                  + f'<div class="pos">{i + 1} de {n} pela {ORDENS[ordem].lower()}'
                  + (" · tracejado: a rede" if rid != REDE else "") + "</div>")
    return corpo + "</div>"


def q_carrossel(f):
    r = por_rota(f)
    rede = total(rd(f))
    if r.empty or rede is None:
        raise SemDado
    rede = rede.copy()
    rede["parte"] = 1.0
    if st.session_state.get("ficha_ordem") not in ORDENS:
        st.session_state.ficha_ordem = "maior"
    ids = ordem_ficha(r, st.session_state.ficha_ordem)
    if st.session_state.get("ficha") not in ids:
        st.session_state.ficha = f["linhas"][0] if len(f["linhas"]) == 1 and f["linhas"][0] in ids else REDE
    c1, c2, c3, c4 = st.columns([1.6, .45, 2.6, .45], gap="small", vertical_alignment="bottom")
    c1.segmented_control("Ordem", list(ORDENS), format_func=ORDENS.get, key="ficha_ordem")
    c2.button("◀", on_click=mover, args=(ids, -1), width="stretch", help="Linha anterior")
    c3.selectbox("Linha", ids, key="ficha", format_func=lambda x: "Rede inteira" if x == REDE else
                 f"{x} · {f['nomes'].get(x, '')}")
    c4.button("▶", on_click=mover, args=(ids, 1), width="stretch", help="Próxima linha")
    ordem = st.session_state.ficha_ordem or "maior"
    i = ids.index(st.session_state.ficha)
    viz = [(k, ids[k]) for k in range(i - 2, i + 3) if 0 <= k < len(ids)]
    serie = series_por_linha(f, [x for _, x in viz if x != REDE])
    base = rd(f)
    datas = sorted(base["data_bh"].unique())
    d = agrega(base, ["data_bh"])
    s = dict(zip(d["data_bh"], d["excesso_min"]))
    serie[REDE] = [s.get(x, np.nan) for x in datas]
    slots = []
    for k in range(i - 2, i + 3):
        if 0 <= k < len(ids):
            slots.append(cartao(ids[k], r, rede, serie, ordem, k, len(ids), k == i, abs(k - i) == 2))
        else:  # sem vizinho: espaco vazio, o carrossel nao da a volta
            slots.append(f'<div class="cartao{" lado2" if abs(k - i) == 2 else ""}" style="visibility:hidden"></div>')
    md('<div class="carro">' + "".join(slots) + "</div>")


def pg_ficha(f):
    painel("f_car", AMBAR, lambda: q_carrossel(f), "01", "LINHAS", "Escolha a linha",
           "Rede inteira primeiro · as setas giram o carrossel na ordem escolhida")
    alvo = st.session_state.get("ficha", REDE)
    linhas = [] if alvo == REDE else [alvo]

    def q_fdia():
        base = rd(f)
        alvo_df = base[base["route_id"].isin(linhas)] if linhas else base
        if alvo_df.empty:
            raise SemDado
        quadro_dia(agrega(alvo_df, ["data_bh"]), total(alvo_df)["excesso_min"], tem_suplementar(linhas), 330)

    st.write("")
    a, b = st.columns([1, 1.6], gap="medium")
    with a:
        painel("f_faixa", AZUL, lambda: md(lista_faixa(faixas_do_recorte(f, linhas))), "02", "HORA DO DIA",
               "Espera por faixa horária", "Azul: com intervalos iguais · âmbar: a espera extra")
    with b:
        painel("f_dia", AMBAR, q_fdia, "03", "DIA A DIA", "Espera extra por dia",
               "Barra clara: dia com evento na cidade · tracejado azul: média do período")


# ---------------------------------------------------------------------------
# 10. O que pesa
# ---------------------------------------------------------------------------
PARTE_MIN_LINHA = 0.001  # linha entra na dispersao com 0,1% ou mais das horas
FAIXAS_LINHAS = [("1 linha", 1, 1), ("2 a 3 linhas", 2, 3), ("4 a 8 linhas", 4, 8), ("9 ou mais", 9, 999)]
LEITURAS = [("Controlar o espaçamento, não só a frota", "Mais ônibus numa linha irregular não a deixa regular."),
            ("Agir linha a linha, não ponto a ponto", "Ponto com muitas linhas não espera mais que os outros."),
            ("Ver o fim de semana à parte", "Roda pouca linha frequente: pesa pouco na média da rede.")]


def relacao(r: float) -> str:
    a = abs(r)
    return ("quase nenhuma relação" if a < .2 else "relação fraca" if a < .4 else "relação moderada" if a < .6
            else "relação forte")


def q_plinhas(f):
    t = metricas(somas(["route_id"], f, alta=True))
    t = t[t["n"] > 0].dropna(subset=["excesso_min"])
    t = t[t["horas"] / t["horas"].sum() >= PARTE_MIN_LINHA]
    if len(t) < 3:
        raise SemDado
    r1 = float(np.corrcoef(t["regular_min"], t["excesso_min"])[0, 1])
    r2 = float(np.corrcoef(t["colados_pct"], t["excesso_min"])[0, 1])
    t["nome"] = t["route_id"].map(f["nomes"]).fillna("")
    hmax = t["horas"].max()
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=.1, subplot_titles=(
        f"<b>INTERVALO ENTRE ÔNIBUS</b><br><span style='font-size:22px;color:{APAGADO}'>r = {br(r1, 2)}</span>"
        f"  <span style='color:{SUAVE}'>{relacao(r1)}</span>",
        f"<b>ÔNIBUS COLADOS</b><br><span style='font-size:22px;color:{VERMELHO}'>r = {br(r2, 2)}</span>"
        f"  <span style='color:{SUAVE}'>{relacao(r2)}</span>"))
    tam = 5 + 18 * np.sqrt(t["horas"] / hmax)
    dica = np.stack([t["route_id"], t["nome"]], axis=1)
    fig.add_scatter(x=t["regular_min"], y=t["excesso_min"], mode="markers", customdata=dica,
                    marker=dict(size=tam, color=APAGADO, opacity=.6, line=dict(width=1, color=FUNDO)),
                    hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>regular %{x:.2f} · extra +%{y:.2f} min"
                                  "<extra></extra>", row=1, col=1)
    fig.add_scatter(x=t["colados_pct"], y=t["excesso_min"], mode="markers", customdata=dica,
                    marker=dict(size=tam, color=VERMELHO, opacity=.6, line=dict(width=1, color=FUNDO)),
                    hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>colados %{x:.1%} · extra +%{y:.2f} min"
                                  "<extra></extra>", row=1, col=2)
    my = float(t["excesso_min"].quantile(.98)) * 1.15
    fig.update_yaxes(range=[0, my], title="espera extra (min)", row=1, col=1)
    fig.update_yaxes(range=[0, my], row=1, col=2)
    fig.update_xaxes(range=[0, float(t["regular_min"].quantile(.98)) * 1.1],
                     title="espera com ônibus regulares (metade do intervalo, min)", row=1, col=1)
    fig.update_xaxes(range=[0, float(t["colados_pct"].quantile(.98)) * 1.1], tickformat=".0%",
                     title="intervalos colados", row=1, col=2)
    for a in fig.layout.annotations:
        a.update(font=dict(size=13, color=SUAVE), yshift=8)
    estilo(fig, 440, legenda=False)
    fig.update_layout(margin=dict(t=78))
    grafico(fig)
    md(f'<div class="rod">{len(t)} linhas. Quem tem intervalo longo não espera mais por isso: a espera extra '
       'acompanha os ônibus colados.</div>')


def q_ppontos(f):
    p = paradas(f)
    rede = extra_de(p)
    itens = []
    for rot, lo, hi in FAIXAS_LINHAS:
        g = p[(p["linhas"] >= lo) & (p["linhas"] <= hi)]
        if g["soma"].sum():
            itens.append((rot, extra_de(g), g["stop_id"].nunique()))
    if not itens:
        raise SemDado
    topo = max(max(e for _, e, _ in itens), rede) * 1.18
    linhas = [[f'<div class="nome"><b>{rot}</b><small>{br(n, 0)} pontos</small></div>',
               barra(e, topo, f"+{br(e, 2)}", AMBAR, ref=rede)] for rot, e, n in itens]
    md(lista("7.5rem minmax(0,1fr)", ["Linhas no ponto", "Espera extra (min)"], linhas)
       + f'<div class="refleg">tracejado: todos os pontos, +{br(rede, 2)}</div>'
       '<div class="rod">A irregularidade vem da linha: o ponto só junta as linhas que passam nele.</div>')


def q_pdias(f):
    df = sel(somas(["route_id", "tipo_dia"], f, tipo=False, linhas=False), f)
    if df.empty:
        raise SemDado
    t = agrega(df, ["tipo_dia"])
    rede = total(df)["excesso_min"]
    htot = t["horas"].sum()
    topo = max(float(t["excesso_min"].max()), rede) * 1.18
    linhas = []
    for cod, rot in TIPOS.items():
        x = t[t["tipo_dia"] == cod]
        if x.empty:
            continue
        x = x.iloc[0]
        linhas.append([f'<div class="nome"><b>{rot}</b></div>',
                       barra(x["excesso_min"], topo, f"+{br(x['excesso_min'], 2)}", AMBAR, ref=rede),
                       f'<span style="color:{SUAVE};font-size:.88rem"><b style="color:{TEXTO}">{pct(x["horas"] / htot)}'
                       f'</b> das horas · <b style="color:{VERMELHO}">{pct(x["colados_pct"], 0)}</b> colados</span>'])
    md(lista("9rem minmax(0,1fr) 13rem", ["Tipo de dia", "Espera extra (min)", "Peso e colados"], linhas,
             "6.5rem minmax(0,1fr)", ocultar=(2,))
       + f'<div class="refleg">tracejado: todos os dias, +{br(rede, 2)}</div>')


def q_leitura():
    md('<div class="passos">' + "".join(f'<div class="p"><i>{i}</i><div><b>{t}</b><span>{s}</span></div></div>'
                                        for i, (t, s) in enumerate(LEITURAS, 1)) + "</div>")


def pg_porque(f):
    a, b = st.columns([1.72, 1], gap="medium")
    with a:
        painel("w_lin", VERMELHO, lambda: q_plinhas(f), "01", "INTERVALO OU COLADOS", "A espera extra segue os colados",
               "Só alta frequência · cada bolha é uma linha com 0,1% ou mais das horas · r: correlação entre as linhas")
    with b:
        painel("w_pts", AMBAR, lambda: q_ppontos(f), "02", "PONTOS", "Ponto cheio não espera mais",
               "Últimos 28 dias, pontos pelo número de linhas · não segue período nem linha")
    st.write("")
    a, b = st.columns([1.72, 1], gap="medium")
    with a:
        painel("w_dias", AZUL, lambda: q_pdias(f), "03", "TIPO DE DIA", "Dia útil, sábado e domingo",
               "Ignora o filtro de tipo de dia · tracejado: todos os dias")
    with b:
        painel("w_leit", VERDE, q_leitura, "04", "LEITURA", "O que muda na prática")


# ---------------------------------------------------------------------------
# 11. Onde agir
# ---------------------------------------------------------------------------
# Trajeto pelo nome da linha (o mesmo criterio de powerbi/modelo.py TRAJETOS): estacao cita uma estacao de
# integracao; centro cita Centro, Savassi ou Hospitais. A busca ignora maiusculas, como CONTAINSSTRING.
TRAJETOS = ["Da estação ao centro", "Do bairro ao centro", "Entre bairros", "Do bairro à estação"]
GRUPO_ROTA = "Da estação ao centro"
VIAS = [("Waldyr Soeiro Emrich", "Av. Waldyr Soeiro Emrich"), ("Cristiano Machado", "Av. Cristiano Machado"),
        ("Raja Gabaglia", "Av. Raja Gabaglia"), ("Ursula Paulino", "R. Úrsula Paulino"),
        ("Nossa Senhora do Carmo", "Av. N. Sra. do Carmo"), ("Amazonas", "Av. Amazonas"),
        ("Dom Pedro II", "Av. Dom Pedro II"), ("Afonso Pena", "Av. Afonso Pena"),
        ("Carlos Luz", "Av. Pres. Carlos Luz"), ("Antonio Carlos", "Av. Pres. Antônio Carlos"),
        ("Contorno", "Av. do Contorno")]
TOP_VIAS = 5


def trajeto(nome: str) -> str:
    n = (nome or "").lower()
    est = "estaç" in n
    cen = any(x in n for x in ("centro", "savassi", "hospita"))
    if est and cen:
        return TRAJETOS[0]
    if cen:
        return TRAJETOS[1]
    if not est:
        return TRAJETOS[2]
    return TRAJETOS[3]


def q_rotas(f):
    r = por_rota(f)
    if r.empty:
        raise SemDado
    r["trajeto"] = r["nome"].map(trajeto)
    g = metricas(r.groupby("trajeto", as_index=False)[SOMAS].sum())
    g["linhas"] = g["trajeto"].map(r.groupby("trajeto")["route_id"].nunique())
    g["parte"] = g["volume_min_h"] / g["volume_min_h"].sum()
    g["hp"] = g["horas"] / g["horas"].sum()
    rede = total(rd(f))["excesso_min"]
    topo = max(float(g["excesso_min"].max()), rede) * 1.12
    linhas = []
    for nome in TRAJETOS:
        x = g[g["trajeto"] == nome]
        if x.empty:
            continue
        x = x.iloc[0]
        linhas.append([f'<div class="nome"><b>{nome}</b><small>{int(x["linhas"])} linhas · {pct(x["hp"], 0)} das horas'
                       '</small></div>', barra(x["excesso_min"], topo, f"+{br(x['excesso_min'], 2)}", AMBAR, ref=rede),
                       f'<span class="num" style="color:{VERMELHO}">{pct(x["colados_pct"])}</span>',
                       f'<span class="num">{pct(x["parte"], 0)}</span>'])
    md(lista("minmax(0,1.15fr) minmax(0,1fr) 4rem 3.6rem", ["Trajeto", "Espera extra (min)", "Colados", "% rede"],
             linhas, "minmax(0,1fr) 7.5rem 3.4rem", ocultar=(3,))
       + f'<div class="refleg">tracejado: a rede, +{br(rede, 2)}</div>')
    top = r[r["trajeto"] == GRUPO_ROTA].head(5)
    md(f'<div class="dois" style="margin-top:1.3rem">AS DE MAIOR PESO ENTRE AS QUE VÃO {GRUPO_ROTA.upper()}</div>'
       + lista("minmax(0,1fr) 4rem 4rem", ["Linha", "Extra", "Colados"],
               [[f'<div class="lin2"><b>{esc(rid)}</b><span class="nome">{esc(n)}</span></div>',
                 f'<span class="num" style="color:{AMBAR}">+{br(e, 2)}</span>',
                 f'<span class="num" style="color:{VERMELHO}">{pct(c)}</span>']
                for rid, n, e, c in zip(top["route_id"], top["nome"], top["excesso_min"], top["colados_pct"])])
       + f'<div class="dois" style="margin-top:1.3rem;color:{VERDE}">O QUE FAZER</div><div class="passos">'
       '<div class="p"><i>1</i><div><b>Seccionar na estação</b><span>A linha leva o passageiro até ela e o tronco segue '
       'ao centro.</span></div></div><div class="p"><i>2</i><div><b>Onde não der: faixa e semáforo no trecho central'
       '</b><span>E ônibus espaçados antes de entrar nele.</span></div></div></div>'
       '<div class="rod" style="margin-top:.9rem">O grupo sai do nome da linha: estação; centro, Savassi ou hospitais. '
       'É associação, não prova de causa: antes de mudar uma rota, conferir trajeto, lotação e onde o passageiro '
       'desce.</div>')


def q_operacao(f):
    t = recorte_total(f)
    r = por_rota(f)
    fx = faixas_do_recorte(f)
    mov = fx[fx["horas"] / fx["horas"].sum() >= .10]
    pior = mov.sort_values(["excesso_min", "ordem_faixa"], ascending=[False, True]).iloc[0]
    melhor = mov.sort_values(["excesso_min", "ordem_faixa"]).iloc[0]
    try:
        p = previsao(f)[["exemplos", "positivos", "alertas", "acertos"]].sum()
        ac = p["acertos"] / p["alertas"]
        vezes = f'{br(ac / (p["positivos"] / p["exemplos"]), 1)}<small>×</small>'
        acerto = pct(ac, 0)
    except SemDado:
        vezes, acerto = "sem dado", "sem dado"
    n80 = linhas_80(r)
    pn, ph = faixa_rotulo(pior["faixa_horaria"])
    mn, _ = faixa_rotulo(melhor["faixa_horaria"])
    itens = [
        (VERDE, f'−{br(t["excesso_min"] * t["reducao_pct"], 2)}<small>min</small>', "por ida ao ponto",
         "Espaçar os ônibus colados no caminho",
         f'Segurar o que encostou no da frente: some {pct(t["reducao_pct"], 0)} da espera extra.',
         "Controle por GPS no ponto. É o Simulador com 100% dos pares."),
        (AMBAR, f"{n80}<small>linhas</small>", f"de {len(r)} medidas", "Começar por poucas linhas",
         "Elas somam 80% da espera extra do recorte.", "O mesmo esforço de controle alcança mais gente nelas."),
        (AMBAR, f'+{br(pior["excesso_min"], 2)}<small>min</small>', f"{pn} ({ph})", f"Reforçar o controle no {pn.lower()}",
         f'A maior espera extra entre as faixas de mais serviço (+{br(melhor["excesso_min"], 2)} no {mn.lower()}).',
         "Fiscal e regulação onde a irregularidade é maior por passageiro."),
        (VERMELHO, pct(t["comboio_pct"], 0), "dos colados", "Despachar com intervalo fixo no terminal",
         "São comboios de 3 ou mais ônibus, que espaçar no caminho não desfaz.",
         "O controle começa na saída do terminal, não só no trajeto."),
        (VERDE, vezes, "a chance sem modelo", "Usar a previsão como lista de prioridade",
         f"Dez paradas antes, os alertas do modelo acertam {acerto}.",
         "Mostrar ao controle os de maior risco, sem ação automática."),
    ]
    md("".join(f'<div class="op"><div><div class="v" style="--c:{c}">{v}</div><div class="s">{s}</div></div>'
               f'<div><b>{t_}</b><span>{l1}</span><em>{l2}</em></div></div>' for c, v, s, t_, l1, l2 in itens))


def q_corredores(f):
    p = paradas(f)
    rede = extra_de(p)
    nomes = p["stop_name"].fillna("").str.lower()
    vias = []
    for k, rot in VIAS:
        g = p[nomes.str.contains(k.lower(), regex=False)]
        if g["soma"].sum() / 3600 >= 5000:
            vias.append((rot, extra_de(g), g["colados"].sum() / g["n"].sum(), g["soma"].sum() / 3600))
    vias = sorted(vias, key=lambda x: (-x[1], x[0]))[:TOP_VIAS]
    if not vias:
        raise SemDado
    topo = max(max(v[1] for v in vias), rede) * 1.15
    linhas = [[f'<span class="k">{i}</span>', f'<div class="nome"><b>{esc(rot)}</b><small>{br(h, 0)} h nos pontos'
               '</small></div>', barra(e, topo, f"+{br(e, 2)}", AZUL, ref=rede),
               f'<span class="num" style="color:{VERMELHO}">{pct(c)}</span>']
              for i, (rot, e, c, h) in enumerate(vias, 1)]
    md(lista("1.4rem minmax(0,1.1fr) minmax(0,1fr) 3.8rem", ["#", "Via", "Espera extra (min)", "Colados"], linhas,
             "1.2rem minmax(0,1fr) 7.5rem", ocultar=(3,))
       + f'<div class="refleg">tracejado: a rede, +{br(rede, 2)}</div>')


def pg_acoes(f):
    a, b = st.columns([1, 1.02], gap="medium")
    with a:
        painel("a_rotas", AMBAR, lambda: q_rotas(f), "01", "ROTAS", "Linhas que vão ao centro esperam mais",
               "Linhas agrupadas pelo trajeto que o nome diz · rede inteira: não segue o filtro de linha")
    with b:
        painel("a_op", VERDE, lambda: q_operacao(f), "02", "OPERAÇÃO", "Cinco ajustes na circulação",
               "Cada número segue o recorte dos filtros · a previsão vem do teste da fase 5")
        st.write("")
        painel("a_vias", AZUL, lambda: q_corredores(f), "03", "CORREDORES", "Onde a via pesa",
               "Últimos 28 dias, média dos pontos da avenida · tracejado: a rede · prioridade começa pela 1ª")


# ---------------------------------------------------------------------------
# Registro: chave -> (rotulo do menu, icone, olho, titulo (palavra em destaque entre * *), funcao)
# ---------------------------------------------------------------------------
PAGINAS = {
    "visao": ("Visão geral", ":material/speed:", "A ESPERA NO PONTO", "Visão *geral*", pg_visao),
    "onde": ("Onde e quando", ":material/grid_view:", "LINHA, FAIXA E DIA", "Onde e *quando*", pg_onde),
    "linhas": ("Linhas", ":material/sort:", "QUEM CONCENTRA A ESPERA", "Linhas", pg_linhas),
    "pontos": ("Pontos", ":material/location_on:", "ÚLTIMOS 28 DIAS", "Pontos", pg_pontos),
    "colados": ("Colados", ":material/directions_bus:", "DOIS DA MESMA LINHA QUASE JUNTOS", "Ônibus *colados*",
                pg_colados),
    "previsao": ("Previsão", ":material/visibility:", "O MODELO DA FASE 5", "Prever os *colados*", pg_previsao),
    "qualidade": ("Confiança", ":material/verified_user:", "QUALIDADE DO DADO", "Dá para *confiar?*", pg_qualidade),
    "simulador": ("Simulador", ":material/tune:", "E SE O CONTROLE AGISSE", "Simulador", pg_simulador),
    "ficha": ("Ficha da linha", ":material/description:", "UMA LINHA POR VEZ", "Ficha da *linha*", pg_ficha),
    "porque": ("O que pesa", ":material/balance:", "O QUE EXPLICA A ESPERA EXTRA", "O que *pesa*", pg_porque),
    "acoes": ("Onde agir", ":material/target:", "O QUE OS NÚMEROS SUGEREM", "Onde *agir*", pg_acoes),
}
