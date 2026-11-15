"""Aparencia do painel web: a mesma linguagem do Power BI (powerbi/arte.py e powerbi/paineis.py).

Fundo tinta, letreiro ambar em Doto, paineis numerados com o numero vazado, e cada cor com um papel so:
ambar = espera extra (o problema), azul = espera regular (a base), verde = ganho e acerto,
vermelho = colados e piora.
"""
import html

import plotly.graph_objects as go
import streamlit as st

from painel.formato import br

# Paleta do Power BI (powerbi/modelo.py)
FUNDO, PAINEL, PAINEL2, BORDA = "#0A0E1C", "#111729", "#182038", "#2A3456"
TEXTO, SUAVE, APAGADO = "#F4F6FB", "#C9D0E4", "#9AA3C2"
AMBAR, AZUL, VERDE, VERMELHO = "#FFB347", "#6AA8FF", "#42D392", "#FF6B6B"
GRADE = "rgba(154,163,194,.14)"

# Escala da espera extra (min): da tinta ao ambar claro. (limite superior, cor); a ultima vale do resto para cima.
ESCALA = [(0.5, "#18203A"), (1.0, "#1F2B47"), (1.5, "#2E3550"), (2.0, "#4A3F4F"), (2.5, "#6E4A45"),
          (3.0, "#94563A"), (3.5, "#B9652F"), (4.5, "#DE7A2C"), (6.0, "#F59A33"), (None, "#FFC15A")]


def esc(s) -> str:
    """Texto vindo do banco, sempre escapado antes de entrar no HTML."""
    return html.escape("" if s is None else str(s))


def cor_escala(v) -> tuple[str, str]:
    """(fundo, letra) da celula pela espera extra."""
    for i, (lim, cor) in enumerate(ESCALA):
        if lim is None or v < lim:
            return cor, (TEXTO if i < 6 else FUNDO)
    return ESCALA[-1][1], FUNDO


def rgb(hexa: str, alfa: int = 230) -> list[int]:
    h = hexa.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alfa]


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Doto:wght@700..900&display=swap');
:root {{ --fundo: {FUNDO}; --painel: {PAINEL}; --painel2: {PAINEL2}; --borda: {BORDA}; --texto: {TEXTO};
         --suave: {SUAVE}; --apagado: {APAGADO}; --ambar: {AMBAR}; --azul: {AZUL}; --verde: {VERDE};
         --vermelho: {VERMELHO}; --curva: cubic-bezier(.2,.8,.2,1); }}
.stApp {{ background:
    radial-gradient(1100px 600px at 100% -10%, rgba(255,179,71,.045), transparent 60%),
    radial-gradient(900px 600px at -10% 0%, rgba(106,168,255,.04), transparent 60%),
    radial-gradient(rgba(201,208,228,.035) 1px, transparent 1.3px) 0 0 / 22px 22px,
    var(--fundo); }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1480px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
@keyframes subir {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes crescer {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@keyframes andar {{ from {{ transform: translateX(-50%); }} to {{ transform: translateX(0); }} }}
@keyframes rolar {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}

/* cabecalho: letreiro e titulo da pagina */
.topo {{ display: flex; flex-wrap: wrap; align-items: center; gap: .8rem 1.6rem; margin-bottom: .9rem; }}
.letreiro {{ display: inline-flex; align-items: center; gap: .8rem; background: #04050B;
             border: 1px solid #3A2C12; border-radius: 12px; padding: .5rem 1.05rem .45rem .55rem;
             box-shadow: inset 0 0 0 3px #0B0C14; }}
.letreiro .placa {{ font-family: 'Doto', monospace; font-weight: 900; font-size: 1.75rem; line-height: 1;
                    color: #04050B; background: var(--ambar); border-radius: 7px; padding: .25rem .42rem .18rem; }}
.letreiro .destino {{ font-family: 'Doto', monospace; font-weight: 800; font-size: 1.9rem; line-height: 1;
                      color: var(--ambar); text-transform: uppercase; letter-spacing: .02em; }}
.pagtit .k {{ color: var(--ambar); font-size: .74rem; font-weight: 800; letter-spacing: .2em; }}
.pagtit .t {{ color: var(--texto); font-size: 2.2rem; font-weight: 800; font-stretch: 75%; line-height: 1.02; }}
.pagtit .t em {{ font-style: normal; color: var(--ambar); }}
.topo .dir {{ margin-left: auto; display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .8rem; }}
.selo {{ display: inline-flex; align-items: center; gap: .5rem; color: var(--suave); font-size: .82rem;
         font-weight: 600; letter-spacing: .06em; background: rgba(66,211,146,.06);
         border: 1px solid rgba(66,211,146,.24); border-radius: 99px; padding: .32rem .8rem; }}
.selo::before {{ content: ""; width: .5rem; height: .5rem; border-radius: 50%; background: var(--verde); }}
.topo a.git {{ color: var(--texto); text-decoration: none; font-size: .86rem; font-weight: 600;
               border: 1px solid var(--borda); border-radius: 99px; padding: .32rem .85rem; }}
.topo a.git:hover {{ border-color: var(--ambar); color: var(--ambar); }}

/* barra fixa: paginas e filtros */
div:has(> .st-key-barra) {{ position: sticky; top: 1.2rem; z-index: 60; padding-top: .4rem; margin-top: 0;
    background: linear-gradient(180deg, var(--fundo) 0, var(--fundo) 55%, transparent 100%); }}
.st-key-barra {{ background: rgba(13,18,36,.9); border: 1px solid var(--borda); border-radius: 16px;
                 padding: .55rem .9rem .2rem; backdrop-filter: blur(12px) saturate(140%);
                 box-shadow: 0 16px 36px -26px rgba(0,0,0,.95); gap: .35rem; }}
.st-key-barra label p {{ color: var(--ambar); font-size: .7rem; font-weight: 800; letter-spacing: .16em;
                         text-transform: uppercase; }}
.st-key-nav button {{ border-radius: 10px !important; border: 1px solid var(--borda) !important;
                      background: rgba(255,255,255,.02) !important; color: var(--suave) !important;
                      font-weight: 600; font-size: .86rem; min-height: 2rem; padding: .15rem .55rem !important; }}
.st-key-nav [data-testid="stButtonGroup"] > div {{ display: grid !important;
    grid-template-columns: repeat(11, minmax(0, 1fr)); gap: .4rem; }}
.st-key-nav button {{ width: 100%; flex-direction: column; gap: .1rem; padding: .35rem .2rem !important;
                      font-size: .78rem !important; line-height: 1.15; white-space: nowrap; overflow: hidden; }}
.st-key-nav button > div, .st-key-nav button > div > span {{ display: flex; flex-direction: column; align-items: center; gap: .1rem; width: 100%;
                            min-width: 0; }}
.st-key-nav button > div > span > span {{ max-width: 100%; min-width: 0; margin: 0 !important; }}
.st-key-nav button p {{ font-size: .78rem !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.st-key-nav button [data-testid="stIconMaterial"] {{ font-size: 1.15rem; }}
@media (max-width: 1100px) {{ .st-key-nav [data-testid="stButtonGroup"] > div {{
    grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); }} }}
.st-key-nav button:hover {{ border-color: var(--ambar) !important; color: var(--texto) !important; }}
.st-key-nav button[kind="pillsActive"], .st-key-nav button[data-testid="stBaseButton-pillsActive"] {{
    background: rgba(255,179,71,.14) !important; border-color: var(--ambar) !important; color: var(--ambar) !important; }}

/* menu lateral */
[data-testid="stSidebar"] {{ background: #0C1122; border-right: 1px solid var(--borda); min-width: 236px !important;
                             max-width: 236px !important; }}
.menu-tit {{ color: var(--ambar); font-size: .7rem; font-weight: 800; letter-spacing: .2em; margin: .2rem 0 .6rem .3rem; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: .25rem; width: 100%; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ width: 100%; margin: 0; padding: .65rem .8rem; border-radius: 10px;
    border: 1px solid transparent; border-left: 3px solid transparent; cursor: pointer; transition: background .15s; }}
[data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [data-testid="stRadio"], [data-testid="stSidebar"] [data-testid="stRadio"] > div,
[data-testid="stSidebar"] [data-testid="stElementContainer"] {{ width: 100% !important; }}
[data-testid="stSidebar"] [role="radiogroup"] label p {{ color: var(--suave); font-size: .98rem; font-weight: 600; }}
[data-testid="stSidebar"] [role="radiogroup"] label [data-testid="stIconMaterial"] {{ font-size: 1.25rem; margin-right: .35rem;
    vertical-align: -4px; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,.04); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: rgba(255,179,71,.12);
    border-color: rgba(255,179,71,.3); border-left-color: var(--ambar); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: var(--ambar); }}

/* paineis numerados */
[class*="st-key-pn_"] {{ --acc: var(--ambar); position: relative; border-radius: 18px; padding: 1.25rem 1.4rem 1.1rem;
    border: 1px solid color-mix(in srgb, var(--acc) 26%, var(--borda));
    background: linear-gradient(170deg, color-mix(in srgb, var(--acc) 4%, var(--painel)), var(--painel) 60%);
    box-shadow: inset 0 1px 0 color-mix(in srgb, var(--acc) 18%, transparent), 0 24px 50px -40px rgba(0,0,0,.9);
    animation: subir .6s var(--curva) both; container-type: inline-size; }}
.ph {{ display: flex; align-items: flex-start; gap: 1rem; margin-bottom: .55rem; }}
.ph .num {{ flex: none; font-size: 3.3rem; font-weight: 700; font-stretch: 75%; line-height: .85; letter-spacing: .01em;
            color: color-mix(in srgb, var(--acc) 5%, var(--painel)); -webkit-text-stroke: 1.6px var(--acc);
            paint-order: stroke fill; opacity: .9; }}
.ph .olho {{ color: var(--acc); font-size: .72rem; font-weight: 800; letter-spacing: .2em; text-transform: uppercase; }}
.ph .tit {{ color: var(--texto); font-size: 1.55rem; font-weight: 800; font-stretch: 78%; line-height: 1.1; }}
.ph .nota {{ color: var(--suave); font-size: .9rem; line-height: 1.4; margin-top: .25rem; }}
.vazio {{ color: var(--apagado); padding: 2rem 0; text-align: center; }}
.rod {{ color: var(--apagado); font-size: .84rem; line-height: 1.45; margin-top: .4rem; }}
.rod b {{ color: var(--suave); }}

/* azulejos: numero grande com rotulo */
.az {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(var(--min, 160px), 1fr)); gap: .8rem; }}
.az .a {{ min-width: 0; border-radius: 14px; padding: .9rem .9rem .85rem; background: var(--painel2); border: 1px solid var(--borda); }}
.az .r {{ color: var(--suave); font-size: .7rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }}
.az .v {{ white-space: nowrap; color: var(--c); font-size: clamp(1.8rem, 6.2cqi, 2.9rem); font-weight: 700; font-stretch: 70%; line-height: 1.05;
          font-variant-numeric: tabular-nums; margin: .15rem 0 .1rem; }}
.az .v small {{ font-size: .45em; font-stretch: 85%; margin-left: .12em; }}
.az .n {{ color: var(--suave); font-size: .86rem; line-height: 1.35; }}

/* lista com barras (ranking, faixas, grupos) */
.lista {{ display: grid; gap: .1rem; }}
.lista .cab, .lista .lin {{ display: grid; grid-template-columns: var(--gc); gap: .7rem; align-items: center; }}
.lista .cab {{ color: var(--suave); font-size: .68rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;
               white-space: nowrap;
               padding-bottom: .3rem; border-bottom: 1px solid var(--borda); }}
.lista .lin {{ padding: .45rem 0; border-bottom: 1px solid rgba(42,52,86,.55); }}
.lista .lin > div, .lista .cab > div {{ min-width: 0; }}
.lista .lin > div {{ overflow: hidden; padding: 4px 0; }}
.lista svg {{ width: 100%; height: 34px; display: block; }}
.lista .lin:last-child {{ border-bottom: 0; }}
.lista .k {{ color: var(--apagado); font-weight: 700; font-stretch: 75%; font-size: 1.05rem; }}
.lista .cod {{ color: var(--texto); font-weight: 800; font-size: 1.02rem; font-variant-numeric: tabular-nums; }}
.lista .nome {{ display: block; color: var(--suave); font-size: .86rem; line-height: 1.25; overflow-wrap: anywhere; }}
.lista span.nome {{ display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
                font-size: .86rem; line-height: 1.25; overflow: hidden; overflow-wrap: anywhere; }}
.lista .lin2 b {{ display: block; color: var(--texto); font-weight: 800; font-size: 1rem; }}
.lista .nome b {{ display: block; color: var(--texto); font-size: 1rem; font-weight: 600; }}
.lista .nome small {{ display: block; color: var(--apagado); font-size: .8rem; }}
.lista .num {{ text-align: right; font-weight: 800; font-stretch: 80%; font-size: 1.12rem; font-variant-numeric: tabular-nums; }}
.barra {{ position: relative; height: 1.45rem; display: flex; align-items: center; gap: .5rem; }}
.barra i {{ display: block; height: 100%; border-radius: 5px; width: var(--w); background: var(--b, var(--ambar));
            transform-origin: left; animation: crescer .9s var(--curva) both; flex: 0 1 auto; min-width: 0; }}
.barra span {{ flex: none; font-weight: 800; font-stretch: 80%; font-size: 1.08rem; color: var(--b, var(--ambar)); white-space: nowrap;
               font-variant-numeric: tabular-nums; }}
.empilha {{ display: flex; height: 1.6rem; border-radius: 6px; overflow: hidden; }}
.empilha i {{ display: flex; align-items: center; padding: 0 .5rem; font-style: normal; font-weight: 800; font-size: .88rem;
              color: var(--fundo); white-space: nowrap; overflow: hidden; transform-origin: left;
              animation: crescer .9s var(--curva) both; }}
.ref {{ position: relative; }}
.ref::after {{ content: ""; position: absolute; top: -4px; bottom: -4px; left: var(--r); width: 0;
               border-left: 2px dashed rgba(244,246,251,.7); }}
.refleg {{ color: var(--suave); font-size: .8rem; margin-top: .35rem; }}

/* mapa de calor em grade */
.calor {{ display: grid; grid-template-columns: var(--gc); gap: 3px; font-variant-numeric: tabular-nums; }}
.calor .h {{ color: var(--suave); font-size: .74rem; font-weight: 700; text-align: center; line-height: 1.2;
             padding-bottom: .25rem; }}
.calor .h small {{ display: block; color: var(--apagado); font-weight: 400; }}
.calor .l {{ color: var(--texto); font-size: .84rem; font-weight: 700; display: flex; align-items: center;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.calor .l.s {{ color: var(--suave); font-weight: 600; }}
.calor .c {{ position: relative; border-radius: 4px; display: flex; align-items: center; justify-content: center;
             font-size: .8rem; font-weight: 600; min-height: 1.5rem; }}
.calor .c.g {{ min-height: 2.6rem; font-size: 1rem; font-weight: 700; }}
.calor .c .d {{ position: absolute; left: 6px; top: 3px; font-size: .64rem; opacity: .7; font-weight: 400; }}
.calor .c .ev {{ position: absolute; right: 5px; top: 5px; width: 8px; height: 8px; border-radius: 50%;
                 background: var(--texto); box-shadow: 0 0 0 1.5px var(--fundo); }}
.escala {{ display: flex; flex-wrap: wrap; align-items: center; gap: .25rem; margin-top: .7rem; color: var(--suave);
           font-size: .78rem; }}
.escala i {{ width: 26px; height: 12px; border-radius: 3px; }}
.escala span {{ margin: 0 .35rem; }}

/* capa (visao geral e previsao) */
.capa {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 1.6rem; align-items: center; }}
.capa .r {{ color: var(--suave); font-size: .8rem; font-weight: 800; letter-spacing: .18em; }}
.capa .rec {{ color: var(--c, var(--ambar)); font-size: .8rem; font-weight: 700; letter-spacing: .1em; margin-top: .35rem; }}
.capa .big {{ white-space: nowrap; color: var(--c, var(--ambar)); font-size: clamp(3.6rem, 13cqi, 8.6rem); font-weight: 700; font-stretch: 70%;
              line-height: .9; letter-spacing: -.01em; margin: .5rem 0 .2rem; font-variant-numeric: tabular-nums; }}
.capa .big small {{ font-size: .32em; margin-left: .15em; }}
.capa .f1 {{ color: var(--texto); font-size: 1.3rem; font-weight: 600; line-height: 1.3; }}
.capa .f1 em {{ font-style: normal; color: var(--c, var(--ambar)); }}
.capa .f2 {{ color: var(--suave); font-size: 1.12rem; margin-top: .15rem; }}
.pilula {{ display: inline-block; margin-top: .9rem; border-radius: 99px; padding: .4rem 1rem; font-weight: 600;
           font-size: .95rem; color: var(--p); border: 1px solid var(--p);
           background: color-mix(in srgb, var(--p) 14%, transparent); }}
.dois {{ color: var(--suave); font-size: .78rem; font-weight: 800; letter-spacing: .14em; margin-bottom: .55rem; }}
.pista-rot {{ display: flex; justify-content: space-between; font-size: .72rem; font-weight: 800; letter-spacing: .14em;
              margin: .55rem 0 .3rem; }}
.pista-rot span {{ color: var(--apagado); }}
.pista {{ position: relative; height: 40px; border-radius: 10px; overflow: hidden; background: #0C1122;
          border: 1px solid var(--borda); }}
.pista::before {{ content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 2px; margin-top: -1px;
                  background: repeating-linear-gradient(90deg, rgba(255,255,255,.15) 0 14px, transparent 14px 28px); }}
.pista::after {{ content: ""; position: absolute; left: 62%; top: 0; bottom: 0; width: 3px; background: var(--suave);
                 opacity: .55; }}
.trilho {{ position: absolute; inset: 0 auto 0 0; width: 200%; z-index: 1; animation: andar 15s linear infinite; }}
.bus {{ position: absolute; top: 50%; width: 34px; height: 17px; margin: -10px 0 0 -17px; border-radius: 4px 8px 8px 4px;
        background: var(--b); }}
.bus::before {{ content: ""; position: absolute; left: 4px; right: 7px; top: 4px; height: 5px; border-radius: 2px;
                background: repeating-linear-gradient(90deg, rgba(5,7,16,.72) 0 5px, transparent 5px 7px); }}
.bus::after {{ content: ""; position: absolute; left: 5px; bottom: -3px; width: 6px; height: 6px; border-radius: 50%;
               background: #C9D0E4; box-shadow: 18px 0 0 #C9D0E4; }}
.ponto {{ color: var(--apagado); font-size: .8rem; margin-top: .3rem; }}
.media {{ margin-top: 1.1rem; }}
.media .t {{ color: var(--suave); font-size: .76rem; font-weight: 800; letter-spacing: .14em; margin-bottom: .35rem; }}
.media .empilha {{ height: 1.9rem; }}
.comp {{ display: grid; gap: .7rem; }}
.comp .q {{ display: flex; justify-content: space-between; color: var(--texto); font-size: 1.05rem; font-weight: 600; }}
.comp .q b {{ color: var(--c); font-variant-numeric: tabular-nums; }}
.comp .t {{ height: 1.5rem; border-radius: 6px; background: rgba(255,255,255,.05); overflow: hidden; }}
.comp .t i {{ display: block; height: 100%; width: var(--w); background: var(--c); border-radius: 6px;
              transform-origin: left; animation: crescer 1s var(--curva) both; }}

/* letreiro rolante */
.rolante {{ display: flex; align-items: stretch; background: #04050B; overflow: hidden; border: 1px solid #3A2C12;
            border-radius: 14px; box-shadow: inset 0 0 0 3px #0B0C14; margin-bottom: .2rem; }}
.rolante .fixo {{ flex: none; display: flex; align-items: center; padding: .55rem 1rem; background: var(--ambar);
                  color: #04050B; font-family: 'Doto', monospace; font-weight: 900; font-size: 1rem;
                  text-transform: uppercase; }}
.rolante .janela {{ flex: 1; overflow: hidden;
                    -webkit-mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent);
                    mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent); }}
.rolante .vai {{ display: flex; width: max-content; animation: rolar 70s linear infinite; }}
.rolante .vai span {{ font-family: 'Doto', monospace; font-weight: 800; font-size: 1.3rem; color: var(--ambar);
                      white-space: nowrap; padding: .55rem 1.2rem; text-transform: uppercase; }}
.rolante .vai span em {{ font-style: normal; color: var(--apagado); }}
.rolante .vai span b {{ color: var(--texto); }}
.rolante:hover .vai {{ animation-play-state: paused; }}

/* eventos numerados */
.eventos .tt {{ color: var(--suave); font-size: .72rem; font-weight: 800; letter-spacing: .14em; margin-bottom: .6rem; }}
.eventos .e {{ display: grid; grid-template-columns: 1.7rem 3rem minmax(0, 1fr); gap: .45rem; align-items: start;
               margin-bottom: .6rem; font-size: .88rem; color: var(--suave); line-height: 1.35; }}
.eventos .e i {{ width: 1.55rem; height: 1.55rem; border-radius: 50%; background: var(--texto); color: var(--fundo);
                 font-style: normal; font-weight: 800; display: flex; align-items: center; justify-content: center;
                 font-size: .82rem; }}
.eventos .e b {{ color: var(--texto); padding-top: .1rem; }}
.eventos .e span {{ padding-top: .1rem; }}

/* carrossel da ficha */
.carro {{ display: grid; grid-template-columns: 1fr 1fr 2.4fr 1fr 1fr; gap: .8rem; align-items: center; }}
.cartao {{ border-radius: 16px; background: var(--painel2); border: 1px solid var(--borda); padding: .9rem 1rem;
           opacity: .55; transform: scale(.94); transition: all .3s var(--curva); min-width: 0; }}
.cartao.centro {{ opacity: 1; transform: none; border-color: var(--ambar);
                  box-shadow: 0 0 0 1px rgba(255,179,71,.25), 0 22px 40px -30px rgba(0,0,0,.9); }}
.cartao .lin {{ display: inline-block; font-family: 'Doto', monospace; font-weight: 900; color: var(--ambar);
                background: #04050B; border: 1px solid #3A2C12; border-radius: 8px; padding: .2rem .5rem;
                font-size: 1.05rem; }}
.cartao .nm {{ color: var(--texto); font-weight: 600; font-size: .92rem; margin-top: .45rem; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }}
.cartao .vv {{ color: var(--ambar); font-size: 2.1rem; font-weight: 700; font-stretch: 70%; line-height: 1.05;
               margin-top: .3rem; }}
.cartao .vv small {{ font-size: .45em; color: var(--suave); margin-left: .2em; }}
.cartao .pos {{ color: var(--apagado); font-size: .78rem; }}
.cartao.centro .vv {{ font-size: 3.4rem; }}
.cartao.centro .nm {{ font-size: 1.05rem; white-space: normal; }}
.cartao .gr {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(4.2rem, 1fr)); gap: .4rem; margin: .55rem 0 .4rem; }}
.cartao .gr div {{ color: var(--suave); font-size: .66rem; font-weight: 800; letter-spacing: .1em; }}
.cartao .gr b {{ display: block; color: var(--texto); font-size: 1.15rem; font-stretch: 80%; letter-spacing: 0;
                  white-space: nowrap; }}
.cartao svg {{ width: 100%; height: 52px; display: block; }}

/* leituras e acoes */
.passos {{ display: grid; gap: .85rem; }}
.passos .p {{ display: grid; grid-template-columns: 1.9rem minmax(0, 1fr); gap: .6rem; }}
.passos .p i {{ width: 1.7rem; height: 1.7rem; border-radius: 50%; border: 1px solid var(--verde); color: var(--verde);
                background: rgba(66,211,146,.14); font-style: normal; font-weight: 800; display: flex;
                align-items: center; justify-content: center; font-size: .9rem; }}
.passos .p b {{ display: block; color: var(--texto); font-size: 1.04rem; font-weight: 600; }}
.passos .p span {{ color: var(--suave); font-size: .92rem; }}
.op {{ display: grid; grid-template-columns: 9.5rem minmax(0, 1fr); gap: 1rem; padding: .75rem 0;
       border-bottom: 1px solid rgba(42,52,86,.7); }}
.op:last-child {{ border-bottom: 0; }}
.op .v {{ color: var(--c); font-size: 2.3rem; font-weight: 700; font-stretch: 72%; line-height: 1; }}
.op .v small {{ font-size: .5em; margin-left: .15em; }}
.op .s {{ color: var(--suave); font-size: .82rem; margin-top: .2rem; }}
.op b {{ display: block; color: var(--texto); font-size: 1.06rem; font-weight: 600; }}
.op span {{ display: block; color: var(--suave); font-size: .93rem; margin-top: .15rem; }}
.op em {{ display: block; font-style: normal; color: var(--apagado); font-size: .88rem; margin-top: .15rem; }}
.r-val {{ display: flex; align-items: baseline; gap: .7rem; }}
.r-val b {{ font-size: 2.4rem; font-weight: 700; font-stretch: 72%; }}
.r-val span {{ color: var(--suave); font-size: .95rem; }}

/* perguntas da confianca */
.perg {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }}
.perg .q {{ border-radius: 16px; background: var(--painel2); border: 1px solid var(--borda); padding: 1.1rem 1.2rem;
            display: flex; flex-direction: column; }}
.perg .q h4 {{ color: var(--texto); font-size: 1.15rem; font-weight: 700; margin: 0; padding: 0; }}
.perg .q .v {{ color: var(--c); font-size: 3.3rem; font-weight: 700; font-stretch: 70%; line-height: 1.05; margin-top: .5rem; }}
.perg .q p {{ color: var(--suave); font-size: .92rem; margin: .1rem 0 0; }}
.perg .q .vd {{ margin-top: .9rem; border-radius: 99px; padding: .45rem .9rem; font-weight: 600; font-size: .92rem;
                color: var(--p); border: 1px solid var(--p); background: color-mix(in srgb, var(--p) 14%, transparent); }}

[data-testid="stCaptionContainer"] p {{ color: var(--apagado); }}
[data-testid="stExpander"] details {{ background: rgba(17,23,41,.7); border-radius: 14px; }}
.rodape {{ color: var(--apagado); font-size: .86rem; margin-top: 2rem; padding-top: 1rem;
           border-top: 1px dashed var(--borda); }}
.rodape a {{ color: var(--ambar); }}

@container (max-width: 720px) {{ .capa {{ grid-template-columns: minmax(0, 1fr); }} }}
@container (max-width: 860px) {{ .perg {{ grid-template-columns: minmax(0, 1fr); }} }}
/* lista larga em quadro estreito (classe qe): usa as colunas do celular, senao o nome da linha some */
@container (max-width: 600px) {{ .lista.qe .cab, .lista.qe .lin {{ grid-template-columns: var(--gcm, var(--gc)); }}
  .lista.qe .oc {{ display: none; }} }}
@media (max-width: 1100px) {{ .carro {{ grid-template-columns: 1fr 2fr 1fr; }} .carro .cartao.lado2 {{ display: none; }} }}
@media (max-width: 900px) {{
  .capa {{ grid-template-columns: minmax(0, 1fr); }}
  .perg {{ grid-template-columns: minmax(0, 1fr); }}
}}
@media (max-width: 640px) {{
  .block-container {{ padding-top: 1.4rem; }}
  .letreiro .destino {{ font-size: 1.3rem; }} .letreiro .placa {{ font-size: 1.2rem; }}
  .pagtit .t {{ font-size: 1.7rem; }}
  div:has(> .st-key-barra) {{ position: static; padding-top: 0; margin-top: 0; background: none; }}
  [class*="st-key-pn_"] {{ padding: 1rem .85rem .9rem; border-radius: 16px; }}
  .ph .num {{ font-size: 2.5rem; }} .ph .tit {{ font-size: 1.3rem; }}
  .az {{ --min: 130px; }} .az .v {{ font-size: 2.2rem; }}
  .lista .cab, .lista .lin {{ grid-template-columns: var(--gcm, var(--gc)); gap: .45rem; }}
  .lista .oc {{ display: none; }}
  .calor .c {{ font-size: .68rem; }} .calor .l {{ font-size: .72rem; }} .calor .h {{ font-size: .62rem; }}
  .carro {{ grid-template-columns: minmax(0, 1fr); }} .carro .cartao:not(.centro) {{ display: none; }}
  .op {{ grid-template-columns: minmax(0, 1fr); gap: .3rem; }}
  .bus {{ width: 24px; height: 13px; margin: -8px 0 0 -12px; }}
  .bus::after {{ left: 3px; width: 5px; height: 5px; box-shadow: 12px 0 0 #C9D0E4; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; }} }}
</style>
"""


def md(texto_html: str):
    st.markdown(texto_html, unsafe_allow_html=True)


def cabeca(num: str, olho: str, titulo: str, nota: str = "") -> str:
    return (f'<div class="ph"><div class="num">{num}</div><div><div class="olho">{olho}</div>'
            f'<div class="tit">{titulo}</div>' + (f'<div class="nota">{nota}</div>' if nota else "") + "</div></div>")


def azulejos(itens, cols: int = 2) -> str:
    """itens: (rotulo, valor, nota, cor). O valor 'numero unidade' vira numero com a unidade menor."""
    partes = []
    for rot, val, nota, cor in itens:
        n, _, u = str(val).partition(" ")
        v = f"{n}<small>{u}</small>" if u else n
        partes.append(f'<div class="a" style="--c:{cor}"><div class="r">{rot}</div><div class="v">{v}</div>'
                      f'<div class="n">{nota}</div></div>')
    return f'<div class="az" style="--min:{100 if cols >= 4 else 200}px">' + "".join(partes) + "</div>"


def barra(v: float, topo: float, texto_: str, cor: str = AMBAR, ref: float | None = None) -> str:
    w = 0 if not topo or v != v else max(0, min(1, v / topo)) * 64
    r = f' ref" style="--r:{ref / topo * 64:.1f}%' if ref is not None and topo else ""
    return (f'<div class="barra{r}" ><i style="--w:{w:.1f}%;--b:{cor}"></i>'
            f'<span style="--b:{cor}">{texto_}</span></div>')


def escala_legenda(titulo: bool = True) -> str:
    partes = []
    ant = 0
    for lim, cor in ESCALA:
        rot = f"{br(ant, 1)} a {br(lim, 1)}" if lim else f"{br(ant, 1)}+"
        partes.append(f'<i style="background:{cor}" title="{rot} min"></i>')
        ant = lim
    return (f'<div class="escala">{"<span>espera extra (min)</span>" if titulo else ""}<span>0</span>'
            + "".join(partes) + "<span>6+</span></div>")


def sparkline(valores: list, w: int = 220, h: int = 44, cor: str = AMBAR, ref: float | None = None,
              topo_min: float = 6) -> str:
    """Mini grafico da espera extra por dia (escala de 0 a 6 min ou ao maximo). Tracejado: a referencia."""
    pts = [(i, v) for i, v in enumerate(valores) if v == v and v is not None]
    if len(pts) < 2:
        return ""
    n = max(1, len(valores) - 1)
    topo = max(topo_min, max(v for _, v in pts))
    y = lambda v: h - 5 - v / topo * (h - 10)  # noqa: E731
    linha = " ".join(f"{4 + i / n * (w - 8):.1f},{y(v):.1f}" for i, v in pts)
    xr = ""
    if ref is not None and ref == ref:
        xr = (f"<line x1='0' x2='{w}' y1='{y(ref):.1f}' y2='{y(ref):.1f}' stroke='{APAGADO}' stroke-width='1' "
              "stroke-dasharray='3 3'/>")
    ux, uy = pts[-1]
    return (f"<svg viewBox='0 0 {w} {h}' preserveAspectRatio='none' xmlns='http://www.w3.org/2000/svg'>{xr}"
            f"<polyline points='{linha}' fill='none' stroke='{cor}' stroke-width='2' stroke-linejoin='round' "
            f"vector-effect='non-scaling-stroke'/><circle cx='{4 + ux / n * (w - 8):.1f}' cy='{y(uy):.1f}' r='3' "
            f"fill='{cor}'/></svg>")


def estilo(fig: go.Figure, altura: int = 380, legenda: bool = True) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Archivo, Segoe UI, sans-serif", color=SUAVE, size=13), separators=",.",
                      margin=dict(l=6, r=6, t=34 if legenda else 10, b=6), height=altura, showlegend=legenda,
                      hoverlabel=dict(font_size=13, font_family="Archivo, sans-serif", bgcolor=PAINEL2,
                                      bordercolor=BORDA),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=TEXTO)))
    fig.update_xaxes(gridcolor=GRADE, zeroline=False, linecolor=BORDA)
    fig.update_yaxes(gridcolor=GRADE, zeroline=False, linecolor=BORDA)
    return fig


def grafico(fig: go.Figure):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "locale": "pt-BR"})
