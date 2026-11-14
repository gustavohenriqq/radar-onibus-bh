"""Arte de fundo das paginas do Power BI, desenhada em HTML e fotografada pelo Edge.

Le o layout de relatorio.py (PAGINAS, TILES, FILTROS) e desenha o que nao muda
com o filtro: menu lateral, letreiro de LED, titulo da pagina, rotulos dos
filtros, molduras e cabecalhos dos paineis, rotulos dos azulejos, legendas e a
molduras dos paineis HTML. Numeros e graficos ficam por cima (paineis.py e visuais nativos).

Mesma linguagem do painel web (painel/app.py): letreiro em Doto ambar, titulos
em Archivo estreito, paineis com numero vazado na cor de cada secao.

Uso: python -I powerbi/arte.py   (grava powerbi/arte/fundo_<pagina>.png)
"""
from __future__ import annotations

import html
import subprocess
import tempfile
import time
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))

from modelo import AMBAR, APAGADO, BORDA, FUNDO, PAINEL, PAINEL2, SUAVE, TEXTO  # noqa: E402
from paineis import para_pagina, proj  # noqa: E402
from relatorio import (FILTRO_H, FILTRO_Y, FILTROS, NAV_ITEM, NAV_TOPO, PAGINAS, POR_CHAVE, TRILHO,  # noqa: E402
                       VISIVEIS, area_html)

SAIDA = PASTA / "arte"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ESCALA_PX = 2  # fundo em 3840 x 2160: nitido quando o Power BI amplia

# Bahnschrift (a DIN das placas, do Windows) nos titulos, a mesma dos paineis HTML; Doto so no letreiro
FONTES = '<link href="https://fonts.googleapis.com/css2?family=Doto:wght@700..900&display=block" rel="stylesheet">'

ICONES = {
    "visao": '<path d="M5 17a8 8 0 1 1 16 0"/><path d="M13 17l4.5-5"/><circle cx="13" cy="17" r="1.6" fill="currentColor"/>',
    "onde": ''.join(f'<rect x="{4 + 6.5 * (i % 3)}" y="{4 + 6.5 * (i // 3)}" width="5" height="5" rx="1.2" '
                    f'fill="currentColor" opacity="{o}" stroke="none"/>'
                    for i, o in enumerate([.35, .7, 1, .55, 1, .4, .9, .45, .25])),
    "linhas": '<path d="M5 7h16M5 12h11M5 17h6"/>',
    "pontos": '<path d="M13 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/><circle cx="13" cy="10" r="2.5"/>',
    "colados": '<rect x="3" y="9" width="9" height="7" rx="2"/><rect x="13" y="9" width="9" height="7" rx="2"/>'
               '<path d="M3 19h20"/>',
    "simulador": '<path d="M5 7h16M5 13h16M5 19h16"/><circle cx="9" cy="7" r="2" fill="#070B1A"/>'
                 '<circle cx="16" cy="13" r="2" fill="#070B1A"/><circle cx="11" cy="19" r="2" fill="#070B1A"/>',
    "previsao": '<path d="M3 13s4-6 10-6 10 6 10 6-4 6-10 6S3 13 3 13z"/><circle cx="13" cy="13" r="3"/>',
    "qualidade": '<path d="M13 3l8 3v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/><path d="M9 13l3 3 5-6"/>',
    "ficha": '<rect x="5" y="3" width="16" height="20" rx="2.5"/><path d="M9 9h8M9 13h8M9 17h5"/>',
    "acoes": '<circle cx="13" cy="13" r="9"/><circle cx="13" cy="13" r="4.5"/>'
             '<circle cx="13" cy="13" r="1.4" fill="currentColor"/>',
    "porque": '<path d="M13 4v18M6 22h14M4 8h18"/><path d="M7 8l-3 7a3 3 0 0 0 6 0zM19 8l-3 7a3 3 0 0 0 6 0z"/>',
}

CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: VARW; height: VARH; overflow: hidden; }}
body {{ position: relative; font-family: 'Bahnschrift', 'Segoe UI', sans-serif; color: {TEXTO}; background: {FUNDO}; }}
.abs {{ position: absolute; }}
.fundo {{ position: absolute; inset: 0; z-index: 0;
  background:
    radial-gradient(900px 520px at 18% -8%, rgba(255,179,71,.07), transparent 70%),
    radial-gradient(800px 600px at 104% 110%, rgba(106,168,255,.08), transparent 70%),
    {FUNDO}; }}
.grade {{ position: absolute; inset: 0; z-index: 0; opacity: .55;
  background-image: linear-gradient(rgba(160,175,230,.035) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(160,175,230,.035) 1px, transparent 1px);
  background-size: 48px 48px; }}
.trilho {{ position: absolute; left: 0; top: 0; bottom: 0; width: {TRILHO}px; z-index: 2;
  background: linear-gradient(180deg, #050713, #04060F); border-right: 1px solid rgba(148,163,255,.10); }}
.placa {{ position: absolute; left: 22px; top: 26px; width: 60px; height: 60px; border-radius: 14px;
  background: #030409; border: 1px solid #2A2410; box-shadow: inset 0 0 0 3px #0A0B12;
  display: flex; align-items: center; justify-content: center;
  font-family: 'Doto', monospace; font-weight: 900; font-size: 26px; color: {AMBAR}; }}
.item {{ position: absolute; left: 0; width: {TRILHO}px; height: {NAV_ITEM}px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 8px; color: {SUAVE}; font-size: 13px; font-weight: 600;
  letter-spacing: .04em; text-transform: uppercase; text-align: center; line-height: 1.15; }}
.item svg {{ width: 28px; height: 28px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round;
  stroke-linejoin: round; }}
.item.ativo {{ color: {TEXTO}; background: linear-gradient(90deg, rgba(255,179,71,.16), transparent); }}
.item.ativo::before {{ content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 4px;
  border-radius: 0 4px 4px 0; background: {AMBAR}; }}
.item.ativo svg {{ color: {AMBAR}; }}
.letreiro {{ position: absolute; left: 136px; top: 30px; height: 70px; display: flex; align-items: center; gap: 16px;
  padding: 0 22px 0 10px; background: #030409; border: 1px solid #2A2410; border-radius: 16px;
  box-shadow: inset 0 0 0 4px #0A0B12, 0 0 40px -12px rgba(255,179,71,.35); }}
.letreiro .bh {{ font-family: 'Doto', monospace; font-weight: 900; font-size: 34px; line-height: 1; color: #030409;
  background: {AMBAR}; border-radius: 9px; padding: 6px 9px 3px; }}
.letreiro .destino {{ font-family: 'Doto', monospace; font-weight: 800; font-size: 34px; line-height: 1;
  color: {AMBAR}; letter-spacing: .02em; text-shadow: 0 0 14px rgba(255,179,71,.55); }}
.kicker {{ position: absolute; left: 592px; top: 26px; color: {AMBAR}; font-size: 15px; font-weight: 700;
  letter-spacing: .18em; }}
.titulo {{ position: absolute; left: 590px; top: 46px; font-size: 48px; font-weight: 700; font-stretch: 87.5%;
  line-height: 1; letter-spacing: -.01em; color: {TEXTO}; white-space: nowrap; }}
.titulo em {{ font-style: normal; color: {AMBAR}; }}
.filtro-rot {{ position: absolute; top: 28px; color: {SUAVE}; font-size: 14px; font-weight: 700; letter-spacing: .12em; }}
.filtro-caixa {{ position: absolute; top: {FILTRO_Y}px; height: {FILTRO_H}px; border-radius: 10px; background: {PAINEL2};
  border: 1px solid {BORDA}; }}
.painel {{ position: absolute; border-radius: 24px; overflow: hidden; z-index: 1;
  border: 1px solid color-mix(in srgb, var(--acc) 16%, rgba(148,163,255,.10));
  background: linear-gradient(180deg, color-mix(in srgb, var(--acc) 8%, {PAINEL}), {PAINEL} 110px);
  box-shadow: inset 0 1px 0 color-mix(in srgb, var(--acc) 30%, transparent), 0 30px 60px -45px rgba(0,0,0,.9); }}
.painel .num {{ position: absolute; left: 24px; top: 18px; font-size: 62px; font-weight: 700; font-stretch: 75%;
  line-height: .85; letter-spacing: .01em; opacity: .9;
  /* contorno so por fora: o miolo pintado na cor do painel esconde as linhas internas da fonte (o cruzamento do 4) */
  color: color-mix(in srgb, var(--acc) 5%, {PAINEL}); -webkit-text-stroke: 2.8px var(--acc); paint-order: stroke fill; }}
.painel .olho {{ position: absolute; left: 96px; top: 18px; color: var(--acc); font-size: 14px; font-weight: 700;
  letter-spacing: .16em; }}
.painel .tit {{ position: absolute; left: 96px; top: 38px; color: {TEXTO}; font-size: 30px; font-weight: 700;
  font-stretch: 87.5%; line-height: 1.1; white-space: nowrap; }}
.painel .nota {{ position: absolute; left: 96px; top: 78px; right: 24px; color: {SUAVE}; font-size: 17px;
  line-height: 1.3; font-family: 'Segoe UI', sans-serif; }}
.rodape {{ position: absolute; left: 136px; bottom: 4px; color: {APAGADO}; font-size: 13px; letter-spacing: .04em; z-index: 3; }}
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def div(classe: str, estilo: str, conteudo: str = "") -> str:
    return f'<div class="{classe}" style="{estilo}">{conteudo}</div>'


def trilho(chave: str) -> str:
    itens = []
    for i, pag in enumerate(VISIVEIS):
        ativo = " ativo" if pag.chave == chave else ""
        rotulo = esc(pag.nome)
        if len(pag.nome) > 10:
            rotulo = rotulo.replace(" e ", " e<br>").replace(" da ", "<br>da ")
        itens.append(f'<div class="item{ativo}" style="top:{NAV_TOPO + i * NAV_ITEM}px">'
                     f'<svg viewBox="0 0 26 26">{ICONES[pag.icone]}</svg><span>{rotulo}</span></div>')
    return '<div class="trilho"><div class="placa">BH</div>' + "".join(itens) + "</div>"


def cabecalho(pag) -> str:
    titulo = esc(pag.titulo) + (f" <em>{esc(pag.destaque)}</em>" if pag.destaque else "")
    partes = ['<div class="letreiro"><span class="bh">BH</span><span class="destino">RADAR DE ÔNIBUS</span></div>',
              f'<div class="kicker">{esc(pag.olho)}</div>', f'<div class="titulo">{titulo}</div>']
    for _, _, _, rotulo, x, w, *_ in FILTROS:
        partes.append(div("filtro-rot", f"left:{x + 2}px", esc(rotulo)))
        partes.append(div("filtro-caixa", f"left:{x}px;width:{w}px"))
    return "".join(partes)


def painel(p) -> str:
    dentro = ""
    if p.titulo:
        dentro = (f'<div class="num">{esc(p.num)}</div><div class="olho">{esc(p.olho)}</div>'
                  f'<div class="tit">{esc(p.titulo)}</div>' + (f'<div class="nota">{esc(p.nota)}</div>' if p.nota else ""))
    return div("painel", f"left:{p.x}px;top:{p.y}px;width:{p.w}px;height:{p.h}px;--acc:{p.cor}", dentro)


def cidade() -> str:
    """Todos os pontos de onibus da rede, apagados, no fundo do mapa (mesma projecao do HTML)."""
    area = area_html(POR_CHAVE["pontos"].p("mapa"))
    _, _, w, h = area
    pontos = []
    for linha in (PASTA / "recursos" / "pontos.csv").read_text(encoding="utf-8").splitlines()[1:]:
        _, lat, lon = linha.split(",")
        x, y = proj(float(lat), float(lon), w, h)
        if 0 <= x <= w and 0 <= y <= h - 70:
            px, py = para_pagina(area, x, y)
            pontos.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="1.6"/>')
    return (f'<svg class="abs" style="left:0;top:0;z-index:2" width="1920" height="1080" viewBox="0 0 1920 1080">'
            f'<g fill="{SUAVE}" fill-opacity=".16">{"".join(pontos)}</g></svg>')


def extras(chave: str) -> str:
    return cidade() if chave == "pontos" else ""


def pagina_html(pag) -> str:
    w, h = pag.largura, pag.altura
    css = CSS.replace("VARW", f"{w}px").replace("VARH", f"{h}px")
    corpo = ('<div class="fundo"></div><div class="grade"></div>' + trilho(pag.chave) + cabecalho(pag)
             + "".join(painel(p) for p in pag.paineis) + extras(pag.chave)
             + '<div class="rodape">Dados: GTFS e GTFS-Realtime da PBH · radar-onibus-bh · projeto independente, '
               'sem vínculo com a Prefeitura</div>')
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">{FONTES}<style>{css}</style></head>'
            f'<body>{corpo}</body></html>')


def fotografar(nome: str, conteudo: str, w: int, h: int) -> Path:
    pasta_html = SAIDA / "html"
    pasta_html.mkdir(parents=True, exist_ok=True)
    arq = pasta_html / f"{nome}.html"
    arq.write_text(conteudo, encoding="utf-8")
    png = SAIDA / f"{nome}.png"
    # O Edge as vezes sai com 0 sem gravar nada: apaga antes, confere depois e tenta de novo com perfil novo
    for _ in range(4):
        png.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="perfil_edge_", ignore_cleanup_errors=True) as perfil:
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={perfil}",
                            "--no-first-run",
                            f"--force-device-scale-factor={ESCALA_PX}", f"--window-size={w},{h}",
                            "--virtual-time-budget=6000", f"--screenshot={png}", arq.as_uri()],
                           check=True, capture_output=True, timeout=180)
            # o PNG pode chegar segundos depois de o processo sair: espera ate 30 s antes de tentar de novo
            for _ in range(30):
                if png.exists() and png.stat().st_size > 0:
                    time.sleep(1)  # termina de gravar
                    return png
                time.sleep(1)
    sys.exit(f"O Edge nao gravou {png.name}")


def main() -> None:
    for pag in PAGINAS:
        png = fotografar(f"fundo_{pag.chave}", pagina_html(pag), pag.largura, pag.altura)
        print(f"{png.name}: {png.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
