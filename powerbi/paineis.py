"""Paineis em HTML: cada um e um SVG montado por uma medida DAX e exibido pelo visual HTML Content.

O SVG usa viewBox no tamanho do painel em unidades da pagina (1920 x 1080) e largura de 100%:
escala junto com a pagina, entao a letra encolhe na mesma proporcao do resto e nada se sobrepoe
numa tela menor. Fontes do sistema (o visual bloqueia @font-face): Bahnschrift, a DIN das placas,
para numeros e rotulos; Segoe UI para frases.

Cada grafico desenha a propria legenda com as mesmas constantes de cor das marcas (modelo.py):
ambar = espera extra, azul = espera regular, verde = ganho e acerto, vermelho = colados e piora.

Regra do arquivo: a medida HTML so formata medidas que ja existem (e sao conferidas contra o SQL);
nenhum numero e recalculado aqui. Ordenar, escolher as N maiores e posicionar e formatacao.
"""
from __future__ import annotations

from modelo import (AMBAR, APAGADO, AZUL, BORDA, ESCALA, FAIXAS, FUNDO, PAINEL, PAINEL2, SUAVE, TEXTO, VERDE, VERMELHO,
                    quebrar)

NUM = "Bahnschrift, DIN Alternate, Segoe UI, sans-serif"
FRASE = "Segoe UI, sans-serif"
M = 8  # margem do viewBox: o visual corta alguns pixels na borda

# Mapa dos pontos: extensao dos pontos com 25 h ou mais (lat -20,028 a -19,776; lon -44,062 a -43,863)
LAT = (-20.036, -19.768)
LON_CENTRO, COS_LAT = -43.9625, 0.940
LEGENDA_MAPA = 78  # faixa de baixo do painel do mapa, reservada para a legenda
TOP_MAPA = 400  # pontos coloridos no mapa (os de maior volume)


# ---------------------------------------------------------------------------
# Montagem do DAX: texto literal do SVG intercalado com trechos DAX
# ---------------------------------------------------------------------------
class D(str):
    """Trecho DAX dentro do SVG (o resto e texto literal)."""


def lit(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def junta(*partes) -> str:
    """Concatena literais e trechos DAX com &, juntando literais vizinhos."""
    saida, buf = [], []
    for p in partes:
        if isinstance(p, D):
            if buf:
                saida.append(lit("".join(buf)))
                buf = []
            saida.append(f"( {p} )")
        else:
            buf.append(str(p))
    if buf:
        saida.append(lit("".join(buf)))
    return "\n    & ".join(saida) if saida else '""'


def c(expr: str, casas: int = 1) -> D:
    """Coordenada com ponto decimal (em pt-BR sairia virgula e o SVG quebra)."""
    padrao = "0." + "0" * casas if casas else "0"
    return D(f'FORMAT ( {expr}, "{padrao}", "en-US" )')


def f(expr: str, padrao: str) -> D:
    """Numero para leitura, na cultura do modelo (pt-BR: virgula decimal)."""
    return D(f'FORMAT ( {expr}, "{padrao}" )')


def esc(expr: str) -> D:
    """Texto do dado escapado para HTML."""
    return D(f'SUBSTITUTE ( SUBSTITUTE ( SUBSTITUTE ( {expr}, "&", "&amp;" ), "<", "&lt;" ), ">", "&gt;" )')


def corta(expr: str, n: int) -> str:
    """Texto com no maximo n caracteres (SVG nao quebra nem corta sozinho)."""
    return f'IF ( LEN ( {expr} ) > {n}, LEFT ( {expr}, {n - 1} ) & "…", {expr} )'


def posicao(t: str, valor: str, chave: str) -> str:
    """Posicao 1..n pelo valor (maior primeiro), desempate pela chave: nunca repete."""
    return (f'VAR _v = [{valor}] VAR _c = {chave} RETURN COUNTROWS ( FILTER ( {t}, [{valor}] > _v || '
            f'( [{valor}] = _v && {chave} < _c ) ) ) + 1')


def svg(w: int, h: int, corpo: str) -> str:
    """Envelope do painel: corpo e uma expressao DAX de texto."""
    abre = (f"<div style='width:100%;height:100%;overflow:hidden'><svg xmlns='http://www.w3.org/2000/svg' "
            f"viewBox='-{M} -{M} {w + 2 * M} {h + 2 * M}' width='100%' height='100%' preserveAspectRatio='xMidYMid meet' "
            f"font-family='{NUM}'>")
    return f"{lit(abre)}\n    & {corpo}\n    & {lit('</svg></div>')}"


def para_pagina(area: tuple[int, int, int, int], x: float, y: float) -> tuple[float, float]:
    """Ponto do SVG de um painel em coordenadas da pagina (a arte usa para casar com o HTML)."""
    ax, ay, w, h = area
    s = min(w / (w + 2 * M), h / (h + 2 * M))
    ox = ax + (w - s * (w + 2 * M)) / 2 + s * M
    oy = ay + (h - s * (h + 2 * M)) / 2 + s * M
    return ox + s * x, oy + s * y


def texto(x, y, conteudo: str, tam: int = 16, cor: str = TEXTO, peso: int = 400, ancora: str = "start",
          fonte: str | None = None, espaco: float = 0) -> str:
    """<text> estatico."""
    extra = (f" font-family='{fonte}'" if fonte else "") + (f" letter-spacing='{espaco}'" if espaco else "")
    return (f"<text x='{x}' y='{y}' font-size='{tam}' font-weight='{peso}' fill='{cor}' text-anchor='{ancora}'"
            f"{extra}>{conteudo}</text>")


def contorno(svg_texto: str) -> str:
    """Texto com contorno da cor do fundo: legivel sobre marcas."""
    return svg_texto.replace("<text ", f"<text stroke='{FUNDO}' stroke-width='4' paint-order='stroke' ", 1)


def abre_texto(x, y, tam: int = 16, cor: str = TEXTO, peso: int = 400, ancora: str = "start",
               fonte: str | None = None, espaco: float = 0) -> str:
    """Abertura de <text> para conteudo dinamico (feche com </text>)."""
    return texto(x, y, "", tam, cor, peso, ancora, fonte, espaco).replace("</text>", "")


def vazio(w: int, h: int, msg: str = "Sem dado no recorte escolhido") -> str:
    return lit(f"<div style='width:100%;height:100%'><svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' "
               f"width='100%' height='100%'>{texto(w // 2, h // 2, msg, 20, SUAVE, 400, 'middle', FRASE)}</svg></div>")


def legenda(x: int, y: int, itens: list[tuple], tam: int = 15) -> str:
    """Legenda em linha. Itens (tipo, cor, rotulo); tipo q = barra, qc = barra clara, l = linha,
    t = tracejado, c = circulo, x = so texto."""
    partes, cx = [], x
    for tipo, cor, rot in itens:
        dx = 0
        if tipo == "q":
            partes.append(f"<rect x='{cx}' y='{y - 12}' width='15' height='15' rx='3' fill='{cor}'/>")
            dx = 23
        elif tipo == "qc":
            partes.append(f"<rect x='{cx}' y='{y - 12}' width='15' height='15' rx='3' fill='{cor}' fill-opacity='.2' "
                          f"stroke='{cor}' stroke-opacity='.5'/>")
            dx = 23
        elif tipo in ("l", "t"):
            traco = " stroke-dasharray='7 5'" if tipo == "t" else ""
            partes.append(f"<line x1='{cx}' x2='{cx + 28}' y1='{y - 5}' y2='{y - 5}' stroke='{cor}' "
                          f"stroke-width='2.5'{traco}/>")
            dx = 36
        elif tipo == "c":
            partes.append(f"<circle cx='{cx + 7}' cy='{y - 5}' r='6' fill='{cor}' stroke='{FUNDO}'/>")
            dx = 21
        partes.append(texto(cx + dx, y, rot, tam, SUAVE, 400, fonte=FRASE))
        cx += dx + round(len(rot) * tam * 0.5) + 30
    return "".join(partes)


def legenda_escala(x: int, y: int, bloco: int = 30, titulo: bool = True) -> str:
    """Escala da espera extra, com os limites embaixo dos blocos."""
    partes, cx = [], x
    if titulo:
        partes.append(texto(cx, y, "ESPERA EXTRA (MIN)", 13, SUAVE, 700, espaco=1.2))
        cx += 176
    rotulos = {0: "0", 2: "1", 4: "2", 6: "3", 8: "4,5", 9: "6+"}
    for i, (_, hx) in enumerate(ESCALA):
        bx = cx + i * (bloco + 2)
        partes.append(f"<rect x='{bx}' y='{y - 13}' width='{bloco}' height='14' rx='3' fill='{hx}' "
                      f"stroke='{BORDA}' stroke-width='.8'/>")
        if i in rotulos:
            partes.append(texto(bx, y + 16, rotulos[i], 13, APAGADO, 600))
    return "".join(partes)


def cor_escala(v: str) -> D:
    """Cor da celula pela espera extra (mesmos degraus da ESCALA)."""
    casos = ", ".join(f'{v} < {lim}, "{hx}"' for lim, hx in ESCALA if lim is not None)
    return D(f'SWITCH ( TRUE (), {casos}, "{ESCALA[-1][1]}" )')


def letra_escala(v: str) -> D:
    """Letra clara nos degraus escuros, escura nos claros."""
    return D(f'IF ( {v} < {ESCALA[5][0]}, "{TEXTO}", "{FUNDO}" )')


def milhoes(expr: str) -> D:
    return D(f'VAR v = {expr} RETURN IF ( v >= 1000000, FORMAT ( v / 1000000, "0.0" ) & " mi", '
             f'IF ( v >= 1000, FORMAT ( v / 1000, "0" ) & " mil", FORMAT ( v, "0" ) ) )')


def azulejo(x: int, y: int, w: int, h: int, rotulo: str, valor: D, nota: str, cor: str) -> list:
    return [f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='16' fill='{PAINEL2}' stroke='{BORDA}'/>",
            f"<rect x='{x}' y='{y + 18}' width='4' height='{h - 36}' rx='2' fill='{cor}'/>",
            texto(x + 22, y + 34, rotulo, 14, SUAVE, 700, espaco=1.5),
            f"<text x='{x + 20}' y='{y + 92}' font-size='52' font-weight='700' fill='{cor}'>", valor, "</text>",
            texto(x + 22, y + h - 16, nota, 15, SUAVE, 400, fonte=FRASE)]


def faixa_numeros(w: int, itens: list, y_rot: int = 52, y_val: int = 126, y_nota: int = 162, tam: int = 64,
                  x0: int = 0, h: int = 190, tam_rot: int = 15, tam_nota: int = 17) -> list:
    """Numeros lado a lado separados por fios: (rotulo, valor D, nota, cor)."""
    col = (w - x0) / len(itens)
    partes = []
    for i, (rot, val, nota, cor) in enumerate(itens):
        xi = round(x0 + i * col)
        if i:
            fim = y_nota + 8 if y_nota else y_val + 10
            partes.append(f"<line x1='{xi}' x2='{xi}' y1='{max(0, y_rot - 22)}' y2='{min(h - 4, fim)}' stroke='{BORDA}'/>")
        x = xi + (34 if i or x0 == 0 else 0)
        partes += [texto(x, y_rot, rot, tam_rot, SUAVE, 700, espaco=1.6 if tam_rot > 13 else 1.1),
                   f"<text x='{x - 2}' y='{y_val}' font-size='{tam}' font-weight='700' fill='{cor}'>", val, "</text>"]
        if nota:
            partes.append(nota if isinstance(nota, D) else texto(x, y_nota, nota, tam_nota, SUAVE, 400, fonte=FRASE))
    return partes


def datas_eixo(t: str, xexpr: str, y: int) -> D:
    """Rotulos de data embaixo do grafico: as segundas-feiras, ou todos os dias se forem ate 10 (usa n)."""
    item = junta("<text x='", c("xd"), f"' y='{y}' font-size='16' fill='{SUAVE}' text-anchor='middle'>",
                 D('FORMAT ( dim_data[data], "dd/mm" )'), "</text>",
                 "<line x1='", c("xd"), "' x2='", c("xd"), f"' y1='{y - 28}' y2='{y - 21}' stroke='{APAGADO}'/>")
    return D(f'CONCATENATEX ( FILTER ( {t}, n <= 10 || WEEKDAY ( dim_data[data], 2 ) = 1 ),\n'
             f'        VAR xd = {xexpr}\n        RETURN {item}, "" )')


# ---------------------------------------------------------------------------
# Visao geral
# ---------------------------------------------------------------------------
def onibus(x: float, y: float, cor: str, esc_: float = 1.15) -> str:
    return (f"<g transform='translate({x:.1f},{y}) scale({esc_})'><rect width='27' height='17' rx='4' fill='{cor}'/>"
            f"<rect x='4' y='3.5' width='17' height='5' rx='1.5' fill='{FUNDO}' fill-opacity='.7'/>"
            f"<circle cx='6.5' cy='18' r='2.8' fill='{TEXTO}'/><circle cx='20.5' cy='18' r='2.8' fill='{TEXTO}'/></g>")


EM_GRUPOS = [0, 9, 18, 27, 55, 64, 73]  # os mesmos 7 onibus da ilustracao do painel web
IGUAIS = [100 / 7 * i for i in range(7)]


def pista(x: int, y: int, w: int, posicoes: list, cor: str, rotulo: str) -> str:
    """Faixa da ilustracao: 7 onibus, em grupos ou espacados, andando, e o ponto marcado.

    Como no painel web: cada onibus aparece duas vezes (uma rua atras) e a faixa anda uma rua
    inteira a cada 15 s, entao a volta emenda sem salto. Animacao em SMIL (animateTransform):
    se o visual nao animar, fica a figura parada.
    """
    ponto = x + w * 0.62
    clip = f"pista{y}"
    partes = [texto(x, y, rotulo, 15, cor, 700, espaco=1.6),
              f"<clipPath id='{clip}'><rect x='{x}' y='{y + 10}' width='{w}' height='50' rx='12'/></clipPath>",
              f"<rect x='{x}' y='{y + 10}' width='{w}' height='50' rx='12' fill='{FUNDO}' stroke='{BORDA}'/>",
              f"<line x1='{x + 8}' x2='{x + w - 8}' y1='{y + 35}' y2='{y + 35}' stroke='{BORDA}' stroke-width='2' "
              "stroke-dasharray='14 12'/>",
              f"<rect x='{ponto:.0f}' y='{y + 10}' width='3' height='50' fill='{TEXTO}' fill-opacity='.8'/>",
              f"<g clip-path='url(#{clip})'><g>"]
    partes += [onibus(x + p / 100 * w + desloc, y + 20, cor) for p in posicoes for desloc in (-w, 0)]
    partes.append(f"<animateTransform attributeName='transform' type='translate' from='0 0' to='{w} 0' "
                  "dur='15s' repeatCount='indefinite'/></g></g>")
    return "".join(partes)


def html_capa(w: int, h: int) -> str:
    """Capa: o numero grande da espera extra, a frase, a variacao e a ilustracao dos onibus."""
    xd = 668  # coluna da direita
    larg = 372
    fixo = (texto(44, 62, "ESPERA EXTRA POR IDA AO PONTO", 17, SUAVE, 700, espaco=2.6)
            + texto(xd, 146, "OS MESMOS ÔNIBUS, DE DOIS JEITOS", 15, SUAVE, 700, espaco=1.8)
            + pista(xd, 178, larg, EM_GRUPOS, AMBAR, "HOJE: EM GRUPOS")
            + pista(xd, 262, larg, IGUAIS, AZUL, "INTERVALOS IGUAIS")
            + texto(xd + larg * 0.62 + 1.5, 170, "o ponto", 14, SUAVE, 400, "middle", FRASE))
    corpo = junta(
        fixo,
        abre_texto(44, 94, 16, AMBAR, 600, espaco=1.2), D("[Recorte]"), "</text>",
        f"<text x='34' y='238' font-size='150' font-weight='700' fill='{AMBAR}'>+", f("ee", "0.00"),
        f"<tspan font-size='48' dx='12'>min</tspan></text>",
        f"<text x='44' y='290' font-size='24' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>de espera "
        f"<tspan fill='{AMBAR}'>a mais</tspan> em cada ida ao ponto,</text>",
        texto(44, 322, "só porque os ônibus não passam em intervalos iguais", 22, SUAVE, 400, fonte=FRASE),
        f"<rect x='44' y='346' width='486' height='38' rx='19' fill-opacity='.14' fill='", D("corv"),
        "' stroke='", D("corv"), "'/>",
        f"<text x='66' y='371' font-size='18' font-weight='600' font-family='{FRASE}' fill='", D("corv"), "'>",
        D("[Texto da variação]"), "</text>",
        # barra da espera media, regular + extra
        f"<text x='{xd}' y='360' font-size='15' font-weight='700' fill='{SUAVE}' letter-spacing='1.6'>"
        "ESPERA MÉDIA NO PONTO: ", f("em", "0.0"), " MIN</text>",
        f"<rect x='{xd}' y='370' width='", c("wr"), f"' height='26' rx='4' fill='{AZUL}'/>",
        "<rect x='", c(f"{xd} + wr"), "' y='370' width='", c(f"{larg} - wr"), f"' height='26' rx='4' fill='{AMBAR}'/>",
        f"<text x='{xd + 10}' y='389' font-size='16' font-weight='700' fill='{FUNDO}'>", f("er", "0.0"),
        " regular</text>",
        "<text x='", c(f"{xd} + wr + ({larg} - wr) / 2"), f"' y='389' font-size='16' font-weight='700' fill='{FUNDO}' "
        "text-anchor='middle'>+", f("ee", "0.0"), "</text>",
    )
    return ("VAR ee = [Espera extra]\nVAR er = [Espera regular]\nVAR em = ee + er\n"
            f"VAR d = [Δ espera extra]\nVAR corv = IF ( d > 0, \"{VERMELHO}\", IF ( d < 0, \"{VERDE}\", \"{SUAVE}\" ) )\n"
            f"VAR wr = DIVIDE ( er, em ) * {larg}\n"
            f"RETURN\n    IF ( ISBLANK ( ee ), {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_numeros(w: int, h: int) -> str:
    """Quatro azulejos: colados, corte sem colagem, intervalos e linhas medidas."""
    g = 16
    tw, th = (w - g) // 2, (h - g) // 2
    itens = [("INTERVALOS COLADOS", f("[Colados]", "0.0%"), "menos de 1/4 do intervalo médio", VERMELHO),
             ("CORTE SEM COLAGEM", f("[Corte sem colagem]", "0%"), "da espera extra sumiria", VERDE),
             ("INTERVALOS MEDIDOS", milhoes("[Intervalos]"), "entre ônibus da mesma linha", AZUL),
             ("LINHAS MEDIDAS", f("[Linhas medidas]", "0"), "com intervalo no recorte", TEXTO)]
    partes = []
    for i, (rot, val, nota, cor) in enumerate(itens):
        partes += azulejo((i % 2) * (tw + g), (i // 2) * (th + g), tw, th, rot, val, nota, cor)
    return f"IF ( ISBLANK ( [Intervalos] ), {vazio(w, h)},\n    {svg(w, h, junta(*partes))} )"


def html_dia(w: int, h: int) -> str:
    """Espera extra por dia (barras), media do periodo e os eventos da cidade numerados."""
    x0, x1 = 50, w - 424  # a lista de eventos ocupa os ultimos 424
    base = h - 62
    alto = base - 30
    lx = x1 + 36  # lista de eventos
    barras = junta(
        "<rect x='", c("x"), "' y='", c(f"{base} - hb"), "' width='", c("bw * 0.72"), "' height='", c("hb"),
        "' rx='2' fill='", D(f'IF ( tem, "{TEXTO}", "{AMBAR}" )'), "'/>",
        D('IF ( primeiro, ' + junta(
            "<line x1='", c("x + bw * 0.36"), "' x2='", c("x + bw * 0.36"), "' y1='", c(f"{base} - hb - 3"),
            "' y2='", c("cy + 12"), f"' stroke='{TEXTO}' stroke-opacity='.45' stroke-dasharray='2 3'/>",
            "<circle cx='", c("x + bw * 0.36"), "' cy='", c("cy"), f"' r='12' fill='{TEXTO}'/>",
            "<text x='", c("x + bw * 0.36"), "' y='", c("cy + 5"),
            f"' font-size='15' font-weight='700' fill='{FUNDO}' text-anchor='middle'>", D("FORMAT ( k, \"0\" )"),
            "</text>") + ' )'))
    grade = junta(
        f"<line x1='{x0}' x2='{x1}' y1='", c("yg"), "' y2='", c("yg"), f"' stroke='{BORDA}' stroke-dasharray='4 6'/>",
        f"<text x='{x0 - 10}' y='", c("yg + 5"), f"' font-size='15' fill='{APAGADO}' text-anchor='end'>",
        D('FORMAT ( [Value], "0" )'), "</text>")
    itens = junta(
        f"<circle cx='{lx + 13}' cy='", c("y - 6"), f"' r='13' fill='{TEXTO}'/>",
        f"<text x='{lx + 13}' y='", c("y - 1"), f"' font-size='15' font-weight='700' fill='{FUNDO}' "
        "text-anchor='middle'>", D('FORMAT ( [@i], "0" )'), "</text>",
        f"<text x='{lx + 36}' y='", c("y"), f"' font-size='16' font-weight='700' fill='{TEXTO}'>",
        D('FORMAT ( [@d], "dd/mm" )'), "</text>",
        f"<text x='{lx + 88}' y='", c("y"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>",
        esc("eventos[evento_l1]"), "</text>",
        f"<text x='{lx + 88}' y='", c("y + 19"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>",
        esc("eventos[evento_l2]"), "</text>",
        f"<text x='{lx + 88}' y='", c("y + 38"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>",
        esc("eventos[evento_l3]"), "</text>")
    corpo = junta(
        D(f'CONCATENATEX ( GENERATESERIES ( passo, topo, passo ),\n        VAR yg = {base} - [Value] / topo * {alto}\n'
          f'        RETURN {grade}, "" )'),
        f"<line x1='{x0}' x2='{x1}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
        f"<text x='{x0 - 10}' y='{base + 5}' font-size='15' fill='{APAGADO}' text-anchor='end'>0</text>",
        D(f'CONCATENATEX ( t,\n        VAR i = INT ( dim_data[data] - d0 )\n'
          f'        VAR x = {x0} + i * bw + bw * 0.14\n        VAR hb = DIVIDE ( [@v], topo ) * {alto}\n'
          '        VAR e = [@e]\n        VAR tem = e <> ""\n'
          '        VAR k = MAXX ( FILTER ( ev2, eventos[evento] = e ), [@i] )\n'
          '        VAR primeiro = tem && dim_data[data] = MAXX ( FILTER ( ev2, eventos[evento] = e ), [@d] )\n'
          '        VAR cy = IF ( MOD ( k, 2 ) = 1, 44, 74 )\n'
          f'        RETURN {barras}, "", dim_data[data], ASC )'),
        # media do periodo
        f"<line x1='{x0}' x2='{x1}' y1='", c("ym"), "' y2='", c("ym"),
        f"' stroke='{AZUL}' stroke-width='2' stroke-dasharray='8 6'/>",
        f"<line x1='{x0}' x2='{x0 + 30}' y1='10' y2='10' stroke='{AZUL}' stroke-width='2' stroke-dasharray='8 6'/>",
        f"<text x='{x0 + 40}' y='16' font-size='16' font-weight='600' fill='{AZUL}'>média do período: ",
        f("med", "0.00"), " min</text>",
        datas_eixo("t", f"{x0} + INT ( dim_data[data] - d0 ) * bw + bw / 2", base + 28),
        abre_texto(x0, h - 4, 14, APAGADO, 400, fonte=FRASE),
        D('IF ( n <= 10, "dias do período", "datas: as segundas-feiras" )'), "</text>",
        # lista de eventos
        texto(lx, 20, "EVENTOS NA CIDADE", 14, SUAVE, 700, espaco=1.5),
        D(f'IF ( COUNTROWS ( ev2 ) = 0,\n        "{texto(lx, 60, "Nenhum evento anotado no período", 15, SUAVE, 400, fonte=FRASE)}",\n'
          # cada evento ocupa as linhas que tem (1 a 3); entra so o que cabe na altura do painel
          f'        CONCATENATEX ( FILTER ( ev3, [@y] + ( eventos[evento_n] - 1 ) * 19 <= {h - 6} ),\n'
          f'            VAR y = [@y]\n            RETURN {itens}, "", [@d], ASC ) )'),
    )
    return (
        'VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@v", [Espera extra],\n'
        '        "@e", CALCULATE ( MAX ( dim_data[evento] ) ) ), NOT ISBLANK ( [@v] ) )\n'
        "VAR d0 = MINX ( t, dim_data[data] )\nVAR d1 = MAXX ( t, dim_data[data] )\n"
        "VAR n = INT ( d1 - d0 ) + 1\nVAR med = [Espera extra]\n"
        "VAR topo = MAX ( 2, CEILING ( MAXX ( t, [@v] ) * 1.3, 1 ) )\nVAR passo = IF ( topo <= 5, 1, 2 )\n"
        f"VAR bw = {x1 - x0} / n\nVAR ym = {base} - med / topo * {alto}\n"
        'VAR evd = FILTER ( eventos, eventos[evento] <> "" && eventos[data] >= d0 && eventos[data] <= d1 )\n'
        "VAR ev = ADDCOLUMNS ( SUMMARIZE ( evd, eventos[evento], eventos[evento_l1], eventos[evento_l2],\n"
        "        eventos[evento_l3], eventos[evento_n] ),\n"
        '        "@d", VAR e = eventos[evento] RETURN MINX ( FILTER ( evd, eventos[evento] = e ), eventos[data] ) )\n'
        'VAR ev2 = ADDCOLUMNS ( ev, "@i", RANKX ( ev, [@d], , ASC, DENSE ) )\n'
        # altura de cada evento na lista: 19 por linha de texto e 12 de folga; o primeiro na altura 51
        'VAR ev3 = ADDCOLUMNS ( ev2, "@y", VAR dd = [@d]\n'
        '        RETURN 51 + SUMX ( FILTER ( ev2, [@d] < dd ), eventos[evento_n] * 19 + 12 ) )\n'
        f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_faixa(w: int, h: int) -> str:
    """Espera por faixa horaria: barra regular + extra, com a espera extra em destaque a direita."""
    bx = 170
    bl = w - bx - 146
    rh = min(80, h // 6)
    linha = junta(
        "<text x='0' y='", c("y + 22"), f"' font-size='18' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>",
        D("dim_faixa[faixa]"), "</text>",
        "<text x='0' y='", c("y + 43"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>",
        D("dim_faixa[horas]"), "</text>",
        f"<rect x='{bx}' y='", c("y + 12"), "' width='", c("wr"), f"' height='26' rx='4' fill='{AZUL}'/>",
        "<rect x='", c(f"{bx} + wr"), "' y='", c("y + 12"), "' width='", c("wx"), f"' height='26' rx='4' fill='{AMBAR}'/>",
        f"<text x='{w}' y='", c("y + 24"), f"' font-size='21' font-weight='700' fill='{AMBAR}' text-anchor='end'>+",
        f("[@x]", "0.00"), "</text>",
        f"<text x='{w}' y='", c("y + 44"), f"' font-size='15' fill='{SUAVE}' text-anchor='end' font-family='{FRASE}'>de ",
        f("[@r] + [@x]", "0.0"), " min</text>")
    corpo = junta(D(
        f'CONCATENATEX ( t,\n        VAR y = ( dim_faixa[ordem] - 1 ) * {rh}\n'
        f'        VAR wr = DIVIDE ( [@r], topo ) * {bl}\n        VAR wx = DIVIDE ( [@x], topo ) * {bl}\n'
        f'        RETURN {linha}, "", dim_faixa[ordem], ASC )'))
    return ('VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_faixa[faixa], dim_faixa[horas], dim_faixa[ordem] ),\n'
            '        "@r", [Espera regular], "@x", [Espera extra] ), NOT ISBLANK ( [@x] ) )\n'
            "VAR topo = MAXX ( t, [@r] + [@x] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Onde e quando: mapas de calor
# ---------------------------------------------------------------------------
def celula(x: str, y: str, cw: float, rh: float, v: str, tam: int = 14) -> str:
    """Celula do mapa de calor: retangulo na cor da escala e o valor no meio."""
    return junta("<rect x='", c(f"{x} + 2"), "' y='", c(f"{y} + 2"), f"' width='{cw - 4:.1f}' height='{rh - 4:.1f}' "
                 "rx='4' fill='", cor_escala(v), "'/>",
                 "<text x='", c(f"{x} + {cw / 2:.1f}"), "' y='", c(f"{y} + {rh / 2 + tam * 0.36:.1f}"),
                 f"' font-size='{tam}' font-weight='600' text-anchor='middle' fill='", letra_escala(v), "'>",
                 f(v, "0.0"), "</text>")


def cabecalho_faixas(lx: float, cw: float, y_nome: int = 18, y_horas: int = 37, tam: int = 14) -> str:
    return "".join(texto(round(lx + i * cw + cw / 2), y_nome, nome, tam, SUAVE, 700, "middle")
                   + texto(round(lx + i * cw + cw / 2), y_horas, horas, tam - 1, APAGADO, 400, "middle")
                   for i, (_, nome, horas) in enumerate(FAIXAS))


def html_calor(w: int, h: int) -> str:
    """As 30 linhas de maior volume x faixa horaria, da maior espera extra para a menor."""
    lx, hy, n = 96, 50, 30
    cw = (w - lx) / 6
    rh = (h - hy - 52) / n
    cel = celula(f"{lx} + ( dim_faixa[ordem] - 1 ) * {cw:.2f}", "y", cw, rh, "v")
    linha = junta(
        "<text x='0' y='", c(f"y + {rh / 2 + 5:.1f}"), f"' font-size='15' font-weight='700' fill='{TEXTO}'>",
        D("dim_linha[route_id]"), "</text>",
        D(f'CONCATENATEX ( ALL ( dim_faixa[ordem] ), VAR v = [Espera extra] RETURN IF ( ISBLANK ( v ), "", {cel} ), "" )'))
    corpo = junta(
        cabecalho_faixas(lx, cw),
        D(f'CONCATENATEX ( r, VAR y = {hy} + ( [@k] - 1 ) * {rh:.2f} RETURN {linha}, "" )'),
        legenda_escala(0, h - 22))
    return (f'VAR t = TOPN ( {n}, FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@v", [Volume], "@e", [Espera extra] ),\n'
            '        NOT ISBLANK ( [@v] ) ), [@v], DESC, dim_linha[route_id], ASC )\n'
            f'VAR r = ADDCOLUMNS ( t, "@k", {posicao("t", "@e", "dim_linha[route_id]")} )\n'
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_calendario(w: int, h: int) -> str:
    """Semanas x dias da semana, com o valor e um ponto branco nos dias de evento (o motivo no title)."""
    lx, hy, leg = 78, 30, 50
    cw = (w - lx) / 7
    dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    cab = (texto(0, 20, "SEMANA", 12, APAGADO, 700, espaco=1.2)
           + "".join(texto(round(lx + i * cw + cw / 2), 20, d, 15, SUAVE, 700, "middle") for i, d in enumerate(dias)))
    cel = junta(
        "<g>", D('IF ( [@e] <> "", "<title>" & ' + esc("[@e]") + ' & "</title>" )'),
        "<rect x='", c("x + 2"), "' y='", c("y + 2"), f"' width='{cw - 4:.1f}' height='", c("rh - 4"),
        "' rx='5' fill='", cor_escala("v"), "'/>",
        "<text x='", c(f"x + {cw / 2:.1f}"), "' y='", c("y + rh / 2 + 7"),
        "' font-size='17' font-weight='700' text-anchor='middle' fill='", letra_escala("v"), "'>", f("v", "0.0"), "</text>",
        "<text x='", c("x + 8"), "' y='", c("y + 16"), "' font-size='12' fill-opacity='.7' fill='", letra_escala("v"),
        "'>", D('FORMAT ( dim_data[data], "dd" )'), "</text>",
        D('IF ( [@e] <> "", ' + junta("<circle cx='", c(f"x + {cw - 12:.1f}"), "' cy='", c("y + 12"),
                                      f"' r='5' fill='{TEXTO}' stroke='{FUNDO}' stroke-width='1.5'/>") + ' )'),
        "</g>")
    semana = junta("<text x='0' y='", c("y + rh / 2 + 6"), f"' font-size='15' fill='{SUAVE}'>",
                   D('FORMAT ( [@s], "dd/mm" )'), "</text>")
    corpo = junta(
        cab,
        D(f'CONCATENATEX ( DISTINCT ( SELECTCOLUMNS ( t, "@s", [@s] ) ), VAR y = {hy} + INT ( ( [@s] - s0 ) / 7 ) * rh '
          f'RETURN {semana}, "" )'),
        D(f'CONCATENATEX ( t, VAR x = {lx} + ( [@w] - 1 ) * {cw:.2f} VAR y = {hy} + INT ( ( [@s] - s0 ) / 7 ) * rh '
          f'VAR v = [@v] RETURN {cel}, "" )'),
        legenda_escala(0, h - 22, 26, False),
        legenda(370, h - 18, [("c", TEXTO, "dia com evento na cidade (passe o mouse)")], 14))
    return ('VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@v", [Espera extra],\n'
            '        "@e", CALCULATE ( MAX ( dim_data[evento] ) ), "@s", CALCULATE ( MAX ( dim_data[semana] ) ),\n'
            '        "@w", WEEKDAY ( dim_data[data], 2 ) ), NOT ISBLANK ( [@v] ) )\n'
            "VAR s0 = MINX ( t, [@s] )\nVAR nw = INT ( ( MAXX ( t, [@s] ) - s0 ) / 7 ) + 1\n"
            f"VAR rh = MIN ( 60, {h - hy - leg} / nw )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_semana(w: int, h: int) -> str:
    """Dia da semana x faixa horaria, na mesma escala de cor."""
    lx, hy = 56, 44
    cw = (w - lx) / 6
    rh = (h - hy) / 7
    cel = celula(f"{lx} + ( dim_faixa[ordem] - 1 ) * {cw:.2f}", "y", cw, rh, "v", 15)
    linha = junta("<text x='0' y='", c(f"y + {rh / 2 + 6:.1f}"), f"' font-size='16' font-weight='700' fill='{SUAVE}'>",
                  D("dim_data[dia_semana]"), "</text>",
                  D(f'CONCATENATEX ( ALL ( dim_faixa[ordem] ), VAR v = [Espera extra] RETURN IF ( ISBLANK ( v ), "", {cel} ), "" )'))
    corpo = junta(cabecalho_faixas(lx, cw, 16, 35, 13),
                  D(f'CONCATENATEX ( ALL ( dim_data[dia_semana_ordem], dim_data[dia_semana] ),\n'
                    f'        VAR y = {hy} + ( dim_data[dia_semana_ordem] - 1 ) * {rh:.2f} RETURN {linha}, "" )'))
    return f"IF ( ISBLANK ( [Espera extra] ), {vazio(w, h)},\n    {svg(w, h, corpo)} )"


# ---------------------------------------------------------------------------
# Linhas: concentracao, quadrantes e ranking
# ---------------------------------------------------------------------------
def html_pareto(w: int, h: int) -> str:
    """Numero de linhas que somam 80% e a curva acumulada das linhas na ordem do volume."""
    x0, x1, top, base = 400, w - 64, 46, h - 46
    alto = base - top
    barras = junta(
        "<rect x='", c("x + bw * 0.1"), "' y='", c(f"{base} - hb"), "' width='", c("bw * 0.8"), "' height='", c("hb"),
        "' fill='", D(f'IF ( [@k] <= n80, "{AMBAR}", "{APAGADO}" )'), "' fill-opacity='",
        D('IF ( [@k] <= n80, ".9", ".45" )'), "'/>")
    rotulo = junta("<text x='", c("x + bw / 2"), f"' y='{base + 22}' font-size='14' fill='{APAGADO}' text-anchor='middle'>",
                   f("[@k]", "0"), "ª</text>")
    grade = "".join(
        f"<line x1='{x0}' x2='{x1}' y1='{base - v * alto:.1f}' y2='{base - v * alto:.1f}' stroke='{cor}' "
        f"stroke-opacity='{op}' stroke-dasharray='6 6'/>"
        + texto(x1 + 10, round(base - v * alto + 5), rot, 15, cor_t, 700 if v == 0.8 else 400)
        for v, rot, cor, op, cor_t in [(0.5, "50%", BORDA, 1, APAGADO), (0.8, "80%", TEXTO, .55, TEXTO),
                                        (1.0, "100%", BORDA, 1, APAGADO)])
    corpo = junta(
        f"<text x='0' y='122' font-size='120' font-weight='700' fill='{AMBAR}'>", f("n80", "0"), "</text>",
        texto(4, 164, "linhas somam 80%", 24, TEXTO, 700, fonte=FRASE),
        texto(4, 194, "da espera extra da rede", 20, SUAVE, 400, fonte=FRASE),
        abre_texto(4, 228, 17, SUAVE, 400, fonte=FRASE), "são ", f("[Linhas para 80% %]", "0%"), " das ",
        f("lr", "0"), " linhas medidas</text>",
        legenda(x0, 16, [("q", AMBAR, "parte de cada linha na espera extra da rede"), ("q", APAGADO, "as 15 seguintes"),
                         ("l", TEXTO, "soma acumulada (eixo à direita)")]),
        grade,
        f"<line x1='{x0}' x2='{x1}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
        texto(x1 + 10, base + 5, "0%", 15, APAGADO),
        D(f'CONCATENATEX ( r, VAR x = {x0} + ( [@k] - 1 ) * bw VAR hb = [@p] / pmax * {alto * 0.6:.0f} RETURN {barras}, "" )'),
        "<polyline points='",
        D(f'CONCATENATEX ( r, FORMAT ( {x0} + ( [@k] - 0.5 ) * bw, "0.0", "en-US" ) & "," & '
          f'FORMAT ( {base} - [@a] * {alto}, "0.0", "en-US" ), " ", [@k], ASC )'),
        f"' fill='none' stroke='{TEXTO}' stroke-width='2.5' stroke-linejoin='round'/>",
        "<line x1='", c(f"{x0} + n80 * bw"), "' x2='", c(f"{x0} + n80 * bw"), f"' y1='{top - 4}' y2='{base}' "
        f"stroke='{AMBAR}' stroke-width='2' stroke-dasharray='6 5'/>",
        "<text x='", c(f"{x0} + n80 * bw - 8"), f"' y='{top + 14}' font-size='15' font-weight='700' fill='{AMBAR}' "
        "text-anchor='end'>até aqui, 80%</text>",
        D(f'CONCATENATEX ( FILTER ( r, [@k] = 1 || MOD ( [@k], 25 ) = 0 ), VAR x = {x0} + ( [@k] - 1 ) * bw RETURN {rotulo}, "" )'),
        texto(x0, h - 2, "linhas na ordem do volume de espera extra (espera extra × horas de serviço) · a maior tem ",
              14, APAGADO, 400, fonte=FRASE).replace("</text>", ""), f("pmax", "0.0%"), " da rede</text>")
    return ("VAR n80 = [Linhas para 80%]\nVAR lr = [Linhas na rede]\n"
            'VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@v", [Volume], "@p", [Parte da espera extra],\n'
            '        "@a", [Parte acumulada] ), NOT ISBLANK ( [@v] ) )\n'
            f'VAR r = FILTER ( ADDCOLUMNS ( t, "@k", {posicao("t", "@v", "dim_linha[route_id]")} ), [@k] <= n80 + 15 )\n'
            f"VAR bw = {x1 - x0} / MAX ( 1, COUNTROWS ( r ) )\nVAR pmax = MAXX ( r, [@p] )\n"
            f"RETURN\n    IF ( COUNTROWS ( r ) = 0 || ISBLANK ( n80 ), {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_quadrantes(w: int, h: int) -> str:
    """Bolhas: colados (x) contra espera extra (y), tamanho pelas horas, cor pelo quadrante da rede."""
    x0, x1, top, base = 70, w - 14, 30, h - 50
    larg, alto = x1 - x0, base - top
    cor = (f'SWITCH ( TRUE (), [@x] >= rx && [@y] >= ry, "{VERMELHO}", [@y] >= ry, "{AMBAR}", '
           f'[@x] >= rx, "{AZUL}", "{APAGADO}" )')
    bolha = junta("<circle cx='", c("px"), "' cy='", c("py"), "' r='", c("rr"), "' fill='", D(cor),
                  f"' fill-opacity='.72' stroke='{FUNDO}' stroke-width='.8'/>")
    nome = junta("<text x='", c("px + rr + 4"), "' y='", c("py + 5"), f"' font-size='14' font-weight='700' fill='{TEXTO}' "
                 f"stroke='{FUNDO}' stroke-width='3' paint-order='stroke'>", D("dim_linha[route_id]"), "</text>")
    pos = (f"VAR px = {x0} + MIN ( [@x] / mx, 1 ) * {larg} VAR py = {base} - MIN ( [@y] / my, 1 ) * {alto} "
           "VAR rr = 2.5 + 9 * SQRT ( DIVIDE ( [@h], mh ) )")
    corpo = junta(
        f"<line x1='{x0}' x2='{x1}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
        f"<line x1='{x0}' x2='{x0}' y1='{top}' y2='{base}' stroke='{APAGADO}'/>",
        "<line x1='", c("xr"), "' x2='", c("xr"), f"' y1='{top}' y2='{base}' stroke='{SUAVE}' stroke-opacity='.6' "
        "stroke-dasharray='6 5'/>",
        f"<line x1='{x0}' x2='{x1}' y1='", c("yr"), "' y2='", c("yr"), f"' stroke='{SUAVE}' stroke-opacity='.6' "
        "stroke-dasharray='6 5'/>",
        D(f'CONCATENATEX ( t, {pos} RETURN {bolha}, "", [@h], DESC )'),
        D(f'CONCATENATEX ( TOPN ( 5, t, [@v], DESC, dim_linha[route_id], ASC ), {pos} RETURN {nome}, "" )'),
        contorno(texto(x1 - 6, top + 16, "muito colado e muita espera", 14, VERMELHO, 700, "end")),
        contorno(texto(x0 + 10, top + 16, "espera alta, pouco colado", 14, AMBAR, 700)),
        contorno(texto(x1 - 6, base - 10, "muito colado, espera baixa", 14, AZUL, 700, "end")),
        contorno(texto(x0 + 10, base - 10, "abaixo da rede nas duas", 14, APAGADO, 700)),
        # eixos
        texto(x0, base + 20, "0%", 14, APAGADO, 400, "middle"),
        "<text x='", c("xr"), f"' y='{base + 20}' font-size='14' fill='{SUAVE}' text-anchor='middle'>rede ",
        f("rx", "0.0%"), "</text>",
        f"<text x='{x1}' y='{base + 20}' font-size='14' fill='{APAGADO}' text-anchor='end'>", f("mx", "0%"), "</text>",
        texto((x0 + x1) // 2, h - 2, "intervalos colados", 15, SUAVE, 400, "middle", FRASE),
        texto(x0 - 8, base + 5, "0", 14, APAGADO, 400, "end"),
        f"<text x='{x0 - 8}' y='", c("yr + 5"), f"' font-size='14' fill='{SUAVE}' text-anchor='end'>",
        f("ry", "0.0"), "</text>",
        f"<text x='{x0 - 8}' y='{top + 5}' font-size='14' fill='{APAGADO}' text-anchor='end'>", f("my", "0"), "</text>",
        f"<text transform='translate(14,{(top + base) // 2}) rotate(-90)' font-size='15' fill='{SUAVE}' "
        f"text-anchor='middle' font-family='{FRASE}'>espera extra (min)</text>")
    return ('VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@x", [Colados], "@y", [Espera extra],\n'
            '        "@h", [Horas de serviço], "@v", [Volume] ), NOT ISBLANK ( [@x] ) && NOT ISBLANK ( [@y] ) )\n'
            "VAR rx = [Colados da rede]\nVAR ry = [Espera extra da rede]\n"
            "VAR mx = MAX ( rx * 2, PERCENTILEX.INC ( t, [@x], 0.98 ) * 1.1 )\n"
            "VAR my = MAX ( ry * 2, PERCENTILEX.INC ( t, [@y], 0.98 ) * 1.1 )\n"
            f"VAR mh = MAXX ( t, [@h] )\nVAR xr = {x0} + rx / mx * {larg}\nVAR yr = {base} - ry / my * {alto}\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_ranking(w: int, h: int) -> str:
    """As 7 linhas de maior volume: posicao, nome, tendencia dia a dia, parte da rede, espera extra e colados."""
    hy, n = 30, 7
    rh = (h - hy) / n
    sx, sl = 300, 150  # mini grafico
    cab = (texto(0, 16, "#", 13, SUAVE, 700) + texto(46, 16, "LINHA", 13, SUAVE, 700, espaco=1.3)
           + texto(sx, 16, "DIA A DIA", 13, SUAVE, 700, espaco=1.3)
           + texto(540, 16, "% DA REDE", 13, SUAVE, 700, "end", espaco=1.3)
           + texto(560, 16, "ESPERA EXTRA (MIN)", 13, SUAVE, 700, espaco=1.3)
           + texto(w, 16, "COLADOS", 13, SUAVE, 700, "end", espaco=1.3))
    linha = junta(
        "<text x='0' y='", c("y + 25"), f"' font-size='16' font-weight='700' fill='{AMBAR}'>", f("[@pos]", "0"), "ª</text>",
        "<text x='46' y='", c("y + 25"), f"' font-size='17' font-weight='700' fill='{TEXTO}'>", D("dim_linha[route_id]"),
        "</text>",
        "<text x='112' y='", c("y + 25"), f"' font-size='14' fill='{SUAVE}' font-family='{FRASE}'>",
        esc(corta("[@nome]", 24)), "</text>",
        "<polyline points='",
        D(f'CONCATENATEX ( sd, FORMAT ( {sx} + DIVIDE ( INT ( dim_data[data] - d0 ), nd ) * {sl}, "0.0", "en-US" ) & "," '
          f'& FORMAT ( y + {rh - 8:.1f} - [@d] / st * {rh - 16:.1f}, "0.0", "en-US" ), " ", dim_data[data], ASC )'),
        f"' fill='none' stroke='{AMBAR}' stroke-width='2' stroke-linejoin='round'/>",
        "<text x='540' y='", c("y + 25"), f"' font-size='16' font-weight='700' fill='{AMBAR}' text-anchor='end'>",
        f("[@p]", "0.0%"), "</text>",
        "<rect x='560' y='", c("y + 14"), "' width='", c("[@e] / emax * 130"), f"' height='14' rx='3' fill='{AMBAR}'/>",
        "<text x='", c("566 + [@e] / emax * 130"), "' y='", c("y + 26"), f"' font-size='16' font-weight='700' fill='{TEXTO}'>",
        f("[@e]", "0.00"), "</text>",
        f"<text x='{w}' y='", c("y + 25"), f"' font-size='16' font-weight='700' fill='{VERMELHO}' text-anchor='end'>",
        f("[@c]", "0.0%"), "</text>",
        "<line x1='0' x2='", str(w), "' y1='", c(f"y + {rh:.1f}"), "' y2='", c(f"y + {rh:.1f}"),
        f"' stroke='{BORDA}' stroke-opacity='.6'/>")
    corpo = junta(cab, D(
        f'CONCATENATEX ( r, VAR y = {hy} + ( [@k] - 1 ) * {rh:.2f}\n'
        '        VAR sd = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@d", [Espera extra] ), NOT ISBLANK ( [@d] ) )\n'
        '        VAR st = MAX ( 6, MAXX ( sd, [@d] ) )\n'
        f'        RETURN {linha}, "", [@k], ASC )'))
    return ('VAR dd = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@x", [Espera extra] ), NOT ISBLANK ( [@x] ) )\n'
            "VAR d0 = MINX ( dd, dim_data[data] )\nVAR nd = MAX ( 1, INT ( MAXX ( dd, dim_data[data] ) - d0 ) )\n"
            f'VAR t = TOPN ( {n}, FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@v", [Volume], "@pos", [Posição],\n'
            '        "@p", [Parte da espera extra], "@e", [Espera extra], "@c", [Colados],\n'
            '        "@nome", CALCULATE ( MAX ( dim_linha[route_long_name] ) ) ), NOT ISBLANK ( [@v] ) ),\n'
            "        [@v], DESC, dim_linha[route_id], ASC )\n"
            f'VAR r = ADDCOLUMNS ( t, "@k", {posicao("t", "@v", "dim_linha[route_id]")} )\n'
            "VAR emax = MAXX ( t, [@e] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Pontos: mapa, numeros e os piores
# ---------------------------------------------------------------------------
def proj(lat: float, lon: float, w: int, h: int) -> tuple[float, float]:
    """Latitude e longitude em coordenadas do SVG do mapa (a arte usa a mesma conta)."""
    k = (h - LEGENDA_MAPA) / (LAT[1] - LAT[0])
    return w / 2 + (lon - LON_CENTRO) * COS_LAT * k, (LAT[1] - lat) * k


def tabela_pontos(n: int) -> str:
    """Os n pontos de maior volume, com a posicao: a mesma ordem no mapa e na tabela."""
    return (f'VAR t0 = FILTER ( ADDCOLUMNS ( VALUES ( fato_paradas[stop_id] ), "@e", [Ponto · mapa espera],\n'
            '        "@v", [Ponto · volume] ), NOT ISBLANK ( [@e] ) )\n'
            f"VAR t = TOPN ( {n}, t0, [@v], DESC, fato_paradas[stop_id], ASC )\n"
            f'VAR r = ADDCOLUMNS ( t, "@k", {posicao("t", "@v", "fato_paradas[stop_id]")} )\n')


def html_mapa(w: int, h: int) -> str:
    """Os pontos de maior volume na cor da espera extra, tamanho pelo volume, os 10 piores numerados."""
    k = (h - LEGENDA_MAPA) / (LAT[1] - LAT[0])
    xy = (f"VAR px = {w / 2} + ( [Ponto · longitude] - ( {LON_CENTRO} ) ) * {COS_LAT * k:.3f} "
          f"VAR py = ( {LAT[1]} - [Ponto · latitude] ) * {k:.3f}")
    ponto = junta("<circle cx='", c("px"), "' cy='", c("py"), "' r='", c("2.2 + 6 * SQRT ( DIVIDE ( [@v], vmax ) )"),
                  "' fill='", cor_escala("[@e]"), f"' stroke='{FUNDO}' stroke-width='.6'/>")
    selo = junta("<circle cx='", c("px"), "' cy='", c("py"), f"' r='11' fill='{TEXTO}' stroke='{FUNDO}' stroke-width='2'/>",
                 "<text x='", c("px"), "' y='", c("py + 4.5"), f"' font-size='13' font-weight='700' fill='{FUNDO}' "
                 "text-anchor='middle'>", f("[@k]", "0"), "</text>")
    ym = h - LEGENDA_MAPA
    corpo = junta(
        f"<g transform='translate({w - 22},18)'><path d='M0,-12 L7,6 L0,2 L-7,6 Z' fill='{SUAVE}'/>"
        f"<text y='22' font-size='13' font-weight='700' fill='{SUAVE}' text-anchor='middle'>N</text></g>",
        D(f'CONCATENATEX ( r, {xy} RETURN {ponto}, "", [@e], ASC )'),
        D(f'CONCATENATEX ( FILTER ( r, [@k] <= 10 ), {xy} RETURN {selo}, "", [@k], DESC )'),
        legenda_escala(0, ym + 30, 28),
        texto(0, ym + 70, f"Os {TOP_MAPA} de maior volume · tamanho: volume · nº: posição na tabela · "
              "cinza: demais pontos", 14, SUAVE, 400, fonte=FRASE))
    return (tabela_pontos(TOP_MAPA) + "VAR vmax = MAXX ( t, [@v] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_pnumeros(w: int, h: int) -> str:
    itens = [("COM 25 H OU MAIS", f("[Pontos no mapa]", "#,0"), None, TEXTO),
             ("ESPERA EXTRA MÉDIA", D('FORMAT ( [Ponto · espera extra rede], "0.00" ) & " min"'), None, AMBAR),
             ("OS 10 PIORES SOMAM", D('FORMAT ( [Top 10 pontos parte], "0.0%" ) & " do total"'), None, VERMELHO),
             ("JANELA", D('SUBSTITUTE ( LOWER ( [Janela dos pontos] ), "de ", "" )'), None, SUAVE)]
    partes = faixa_numeros(w, itens, 18, 70, 0, 40, h=h)
    return f"IF ( ISBLANK ( [Pontos no mapa] ), {vazio(w, h)},\n    {svg(w, h, junta(*partes))} )"


def html_piores(w: int, h: int) -> str:
    """Os 10 pontos de maior volume, com o mesmo numero do mapa."""
    hy = 34
    rh = (h - hy) / 10
    cab = "".join(texto(x, 16, t, 13, SUAVE, 700, a, espaco=1.2) for x, t, a in [
        (0, "Nº", "start"), (44, "CÓDIGO", "start"), (118, "PONTO", "start"), (470, "LINHAS", "end"),
        (568, "REGULAR", "end"), (590, "ESPERA EXTRA (MIN)", "start"), (880, "COLADOS", "end"), (w, "% DO TOTAL", "end")])
    yt = f"y + {rh / 2 + 6:.1f}"
    linha = junta(
        "<circle cx='14' cy='", c(f"y + {rh / 2:.1f}"), f"' r='14' fill='{TEXTO}'/>",
        "<text x='14' y='", c(f"y + {rh / 2 + 5:.1f}"), f"' font-size='15' font-weight='700' fill='{FUNDO}' "
        "text-anchor='middle'>", f("[@k]", "0"), "</text>",
        "<text x='44' y='", c(yt), f"' font-size='15' fill='{SUAVE}'>", D("fato_paradas[stop_id]"), "</text>",
        "<text x='118' y='", c(yt), f"' font-size='16' fill='{TEXTO}' font-family='{FRASE}'>",
        esc(corta("[@nome]", 36)), "</text>",
        "<text x='470' y='", c(yt), f"' font-size='16' fill='{SUAVE}' text-anchor='end'>", f("[@l]", "0"), "</text>",
        "<text x='568' y='", c(yt), f"' font-size='16' fill='{AZUL}' text-anchor='end'>", f("[@r]", "0.00"), "</text>",
        "<rect x='590' y='", c(f"y + {rh / 2 - 7:.1f}"), "' width='", c("[@e] / emax * 150"),
        f"' height='14' rx='3' fill='{AMBAR}'/>",
        "<text x='", c("598 + [@e] / emax * 150"), "' y='", c(yt), f"' font-size='16' font-weight='700' fill='{TEXTO}'>",
        f("[@e]", "0.00"), "</text>",
        "<text x='880' y='", c(yt), f"' font-size='16' fill='{VERMELHO}' text-anchor='end'>", f("[@c]", "0.0%"), "</text>",
        f"<text x='{w}' y='", c(yt), f"' font-size='16' font-weight='700' fill='{AMBAR}' text-anchor='end'>",
        f("[@p]", "0.0%"), "</text>",
        "<line x1='0' x2='", str(w), "' y1='", c(f"y + {rh:.1f}"), "' y2='", c(f"y + {rh:.1f}"),
        f"' stroke='{BORDA}' stroke-opacity='.6'/>")
    corpo = junta(cab, D(
        f'CONCATENATEX ( r10, VAR y = {hy} + ( [@k] - 1 ) * {rh:.2f} RETURN {linha}, "", [@k], ASC )'))
    return (tabela_pontos(10)
            + 'VAR r10 = ADDCOLUMNS ( r, "@nome", CALCULATE ( MAX ( fato_paradas[stop_name] ) ), "@l", [Ponto · linhas],\n'
              '        "@r", [Ponto · espera regular], "@c", [Ponto · colados], "@p", [Ponto · parte] )\n'
              "VAR emax = MAXX ( r10, [@e] )\n"
              f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Colados
# ---------------------------------------------------------------------------
def html_cnum(w: int, h: int) -> str:
    itens = [("INTERVALOS COLADOS", f("[Colados]", "0.0%"), "menos de 1/4 do intervalo médio", VERMELHO),
             ("ABAIXO DE 60 SEGUNDOS", f("[Abaixo de 60 s]", "0.0%"), "dos intervalos: praticamente juntos", VERMELHO),
             ("COMBOIOS", f("[Colados atrás de colado %]", "0%"), "dos colados são o 3º ônibus em diante", TEXTO),
             ("CORTE SEM COLAGEM", f("[Corte sem colagem]", "0%"), "da espera extra sumiria sem colagem", VERDE)]
    return f"IF ( ISBLANK ( [Intervalos] ), {vazio(w, h)},\n    {svg(w, h, junta(*faixa_numeros(w, itens, h=h)))} )"


def html_hist(w: int, h: int) -> str:
    """Histograma do intervalo dividido pelo intervalo medio, colados em vermelho."""
    x0, x1, top, base = 64, w - 14, 76, h - 74
    n = 81
    bw = (x1 - x0) / n
    alto = base - top

    def xc(k: int) -> float:
        return x0 + k * bw + bw / 2

    marcas = [(0, "0"), (5, "0,25"), (10, "0,5"), (20, "1"), (30, "1,5"), (40, "2"), (60, "3"), (80, "4 ou mais")]
    fixo = "".join([
        legenda(0, 18, [("q", VERMELHO, "colados: menos de 1/4 do intervalo médio"), ("q", AZUL, "demais intervalos"),
                        ("t", TEXTO, "intervalo igual ao médio")]),
        f"<rect x='{x0}' y='{top - 26}' width='{5 * bw:.1f}' height='{base - top + 26}' fill='{VERMELHO}' "
        "fill-opacity='.08'/>",
        texto(x0 + 6, top - 9, "COLADOS", 13, VERMELHO, 700, espaco=1.2),
        f"<line x1='{xc(20):.1f}' x2='{xc(20):.1f}' y1='{top - 26}' y2='{base}' stroke='{TEXTO}' stroke-opacity='.75' "
        "stroke-dasharray='7 5' stroke-width='2'/>",
        texto(round(xc(20)) + 8, top - 9, "INTERVALO MÉDIO", 13, TEXTO, 700, espaco=1.2),
        f"<line x1='{x0}' x2='{x1}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
        texto(x0 - 10, base + 5, "0", 15, APAGADO, 400, "end"),
        *[texto(round(xc(k)), base + 26, r, 16, SUAVE, 400, "middle")
          + f"<line x1='{xc(k):.1f}' x2='{xc(k):.1f}' y1='{base}' y2='{base + 7}' stroke='{APAGADO}'/>" for k, r in marcas],
        texto((x0 + x1) // 2, base + 60, "tamanho do intervalo dividido pelo intervalo médio do grupo (1 = igual ao médio)",
              16, SUAVE, 400, "middle", FRASE)])
    grade = junta(
        f"<line x1='{x0}' x2='{x1}' y1='", c("yg"), "' y2='", c("yg"), f"' stroke='{BORDA}' stroke-dasharray='4 6'/>",
        f"<text x='{x0 - 10}' y='", c("yg + 5"), f"' font-size='15' fill='{APAGADO}' text-anchor='end'>",
        D('FORMAT ( v, IF ( passo < 0.01, "0.0%", "0%" ) )'), "</text>")
    barra = junta("<rect x='", c(f"{x0} + dim_classe[classe] * {bw:.4f} + {bw * 0.12:.2f}"), "' y='", c(f"{base} - hb"),
                  f"' width='{bw * 0.76:.2f}' height='", c("hb"), "' rx='1.5' fill='",
                  D(f'IF ( dim_classe[classe] < 5, "{VERMELHO}", "{AZUL}" )'), "'/>")
    corpo = junta(
        fixo,
        D(f'CONCATENATEX ( GENERATESERIES ( 1, ROUND ( topo / passo, 0 ), 1 ), VAR v = [Value] * passo '
          f'VAR yg = {base} - v / topo * {alto} RETURN {grade}, "" )'),
        D(f'CONCATENATEX ( t, VAR hb = [@p] / topo * {alto} RETURN {barra}, "" )'))
    return ('VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_classe[classe] ), "@p", [% dos intervalos] ), NOT ISBLANK ( [@p] ) )\n'
            "VAR mx = MAXX ( t, [@p] )\nVAR passo = IF ( mx > 0.06, 0.02, IF ( mx > 0.03, 0.01, 0.005 ) )\n"
            "VAR topo = CEILING ( mx * 1.1 / passo, 1 ) * passo\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_cfaixa(w: int, h: int) -> str:
    bx = 168
    bl = w - bx - 84
    rh = h / 6
    linha = junta(
        "<text x='0' y='", c(f"y + {rh / 2 + 6:.1f}"), f"' font-size='16' fill='{TEXTO}' font-family='{FRASE}'>",
        D("dim_faixa[faixa]"), "</text>",
        f"<rect x='{bx}' y='", c(f"y + {rh / 2 - 8:.1f}"), "' width='", c(f"[@c] / topo * {bl}"),
        f"' height='16' rx='4' fill='{VERMELHO}'/>",
        f"<text x='{w}' y='", c(f"y + {rh / 2 + 6:.1f}"), f"' font-size='18' font-weight='700' fill='{VERMELHO}' "
        "text-anchor='end'>", f("[@c]", "0.0%"), "</text>")
    corpo = junta(D(f'CONCATENATEX ( t, VAR y = ( dim_faixa[ordem] - 1 ) * {rh:.2f} RETURN {linha}, "" )'))
    return ('VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_faixa[faixa], dim_faixa[ordem] ), "@c", [Colados] ), NOT ISBLANK ( [@c] ) )\n'
            "VAR topo = MAXX ( t, [@c] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_clinhas(w: int, h: int) -> str:
    n = 5
    rh = h / n
    bl = w - 200
    linha = junta(
        "<text x='0' y='", c("y + 20"), f"' font-size='17' font-weight='700' fill='{TEXTO}'>", D("dim_linha[route_id]"),
        "</text>",
        "<text x='76' y='", c("y + 20"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>",
        esc(corta("[@nome]", 44)), "</text>",
        f"<text x='{w}' y='", c("y + 20"), f"' font-size='17' font-weight='700' fill='{VERMELHO}' text-anchor='end'>",
        f("[@n]", "#,0"), "</text>",
        "<rect x='0' y='", c("y + 29"), "' width='", c(f"[@n] / topo * {bl}"), f"' height='9' rx='3' fill='{VERMELHO}'/>",
        f"<text x='{w}' y='", c("y + 40"), f"' font-size='14' fill='{SUAVE}' text-anchor='end'>",
        f("[@c]", "0.0%"), " dos intervalos</text>")
    corpo = junta(D(f'CONCATENATEX ( r, VAR y = ( [@k] - 1 ) * {rh:.2f} RETURN {linha}, "" )'))
    return ('VAR t = TOPN ( 5, FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@n", [Intervalos colados],\n'
            '        "@c", [Colados], "@nome", CALCULATE ( MAX ( dim_linha[route_long_name] ) ) ), [@n] > 0 ),\n'
            "        [@n], DESC, dim_linha[route_id], ASC )\n"
            f'VAR r = ADDCOLUMNS ( t, "@k", {posicao("t", "@n", "dim_linha[route_id]")} )\n'
            "VAR topo = MAXX ( t, [@n] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Previsao (fase 5)
# ---------------------------------------------------------------------------
def html_pv_capa(w: int, h: int) -> str:
    xd, larg = 668, 372
    fixo = (texto(44, 62, "ACERTO DOS ALERTAS", 17, SUAVE, 700, espaco=2.6)
            + f"<text x='44' y='290' font-size='24' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>dos alertas "
              f"chegaram <tspan fill='{VERDE}'>colados</tspan> de fato</text>"
            + texto(44, 322, "testado uma vez, em dias que o modelo não tinha visto", 22, SUAVE, 400, fonte=FRASE)
            + f"<rect x='44' y='346' width='500' height='38' rx='19' fill='{VERDE}' fill-opacity='.14' stroke='{VERDE}'/>"
            + texto(66, 371, "Uso sugerido: lista de prioridade para o controle", 18, VERDE, 600, fonte=FRASE)
            + texto(xd, 146, "COM E SEM O MODELO", 15, SUAVE, 700, espaco=1.8)
            + texto(xd, 188, "Ônibus qualquer chega colado", 19, TEXTO, 600, fonte=FRASE)
            + texto(xd, 272, "Ônibus com alerta chega colado", 19, TEXTO, 600, fonte=FRASE)
            + f"<rect x='{xd}' y='200' width='{larg}' height='32' rx='6' fill='{BORDA}' fill-opacity='.5'/>"
            + f"<rect x='{xd}' y='284' width='{larg}' height='32' rx='6' fill='{BORDA}' fill-opacity='.5'/>")
    corpo = junta(
        fixo,
        abre_texto(44, 94, 16, VERDE, 600, espaco=1.2), D("[Janela do teste]"), "</text>",
        f"<text x='34' y='238' font-size='150' font-weight='700' fill='{VERDE}'>", f("ac", "0%"), "</text>",
        f"<rect x='{xd}' y='200' width='", c(f"ch * {larg}"), f"' height='32' rx='6' fill='{APAGADO}'/>",
        abre_texto(xd + larg, 188, 19, APAGADO, 700, "end"), f("ch", "0.0%"), "</text>",
        f"<rect x='{xd}' y='284' width='", c(f"ac * {larg}"), f"' height='32' rx='6' fill='{VERDE}'/>",
        abre_texto(xd + larg, 272, 19, VERDE, 700, "end"), f("ac", "0.0%"), "</text>",
        f"<text x='{xd}' y='372' font-size='34' font-weight='700' fill='{VERDE}'>", f("[Vezes a chance]", "0.0"),
        f"×<tspan font-size='19' font-weight='400' fill='{SUAVE}' font-family='{FRASE}' dx='10'>"
        "a chance de um ônibus qualquer</tspan></text>")
    return ("VAR ac = [Acerto dos alertas]\nVAR ch = [Chance sem modelo]\n"
            f"RETURN\n    IF ( ISBLANK ( ac ), {vazio(w, h, 'Sem alerta do modelo no recorte')},\n    {svg(w, h, corpo)} )")


def html_pv_num(w: int, h: int) -> str:
    g = 16
    tw, th = (w - g) // 2, (h - g) // 2
    itens = [("ALERTAS", f("[Alertas]", "#,0"), "passagens apontadas pelo modelo", TEXTO),
             ("ACERTOS", f("[Acertos]", "#,0"), "chegaram colados de fato", VERDE),
             ("COLADOS AVISADOS", f("[Colados avisados]", "0%"), "dos colados tiveram alerta", TEXTO),
             ("PASSAGENS NO TESTE", milhoes("[Exemplos]"), "ônibus avaliados pelo modelo", TEXTO)]
    partes = []
    for i, (rot, val, nota, cor) in enumerate(itens):
        partes += azulejo((i % 2) * (tw + g), (i // 2) * (th + g), tw, th, rot, val, nota, cor)
    return f"IF ( ISBLANK ( [Alertas] ), {vazio(w, h)},\n    {svg(w, h, junta(*partes))} )"


def html_pv_dia(w: int, h: int) -> str:
    x0, x1, top, base = 64, w - 10, 64, h - 58
    alto = base - top
    grade = junta(
        f"<line x1='{x0}' x2='{x1}' y1='", c("yg"), "' y2='", c("yg"), f"' stroke='{BORDA}' stroke-dasharray='4 6'/>",
        f"<text x='{x0 - 10}' y='", c("yg + 5"), f"' font-size='15' fill='{APAGADO}' text-anchor='end'>",
        f("v", "#,0"), "</text>")
    dia = junta(
        "<rect x='", c("x"), "' y='", c(f"{base} - ha"), "' width='", c("bw * 0.64"), "' height='", c("ha"),
        f"' rx='3' fill='{TEXTO}' fill-opacity='.2' stroke='{TEXTO}' stroke-opacity='.4'/>",
        "<rect x='", c("x"), "' y='", c(f"{base} - hc"), "' width='", c("bw * 0.64"), "' height='", c("hc"),
        f"' rx='3' fill='{VERDE}'/>",
        "<text x='", c("x + bw * 0.32"), "' y='", c(f"{base} - ha - 10"), f"' font-size='16' font-weight='700' "
        f"fill='{VERDE}' text-anchor='middle'>", f("[@p]", "0%"), "</text>",
        "<text x='", c("x + bw * 0.32"), f"' y='{base + 26}' font-size='16' fill='{SUAVE}' text-anchor='middle'>",
        D('FORMAT ( dim_data[data], "dd/mm" )'), "</text>",
        "<text x='", c("x + bw * 0.32"), f"' y='{base + 46}' font-size='13' fill='{APAGADO}' text-anchor='middle'>",
        D('FORMAT ( dim_data[data], "ddd" )'), "</text>")
    corpo = junta(
        legenda(0, 18, [("qc", TEXTO, "alertas do dia"), ("q", VERDE, "chegaram colados"),
                        ("x", None, "o número acima da barra é o acerto do dia")]),
        D(f'CONCATENATEX ( GENERATESERIES ( 1, ROUND ( topo / passo, 0 ), 1 ), VAR v = [Value] * passo '
          f'VAR yg = {base} - v / topo * {alto} RETURN {grade}, "" )'),
        f"<line x1='{x0}' x2='{x1}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
        D(f'CONCATENATEX ( t, VAR x = {x0} + INT ( dim_data[data] - d0 ) * bw + bw * 0.18 '
          f'VAR ha = [@a] / topo * {alto} VAR hc = [@c] / topo * {alto} RETURN {dia}, "" )'))
    return ('VAR t = FILTER ( CALCULATETABLE ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@a", [Alertas no dia],\n'
            '        "@c", [Acertos no dia], "@p", [Acerto no dia] ), REMOVEFILTERS ( sel_periodo ), REMOVEFILTERS ( dim_data ) ),\n'
            "        [@a] > 0 )\n"
            "VAR d0 = MINX ( t, dim_data[data] )\nVAR n = INT ( MAXX ( t, dim_data[data] ) - d0 ) + 1\n"
            f"VAR bw = {x1 - x0} / n\nVAR mx = MAXX ( t, [@a] )\n"
            "VAR passo = IF ( mx > 8000, 4000, IF ( mx > 4000, 2000, IF ( mx > 2000, 1000, IF ( mx > 800, 500, 100 ) ) ) )\n"
            "VAR topo = CEILING ( mx * 1.18 / passo, 1 ) * passo\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_pv_linhas(w: int, h: int) -> str:
    hy, n = 30, 6
    rh = (h - hy) / n
    bl = w - 160
    cab = texto(0, 14, "LINHA", 13, SUAVE, 700, espaco=1.3) + texto(w, 14, "ALERTAS · ACERTO", 13, SUAVE, 700, "end",
                                                                    espaco=1.3)
    linha = junta(
        "<text x='0' y='", c("y + 20"), f"' font-size='17' font-weight='700' fill='{TEXTO}'>", D("dim_linha[route_id]"),
        "</text>",
        "<text x='76' y='", c("y + 20"), f"' font-size='14' fill='{SUAVE}' font-family='{FRASE}'>",
        esc(corta("[@nome]", 40)), "</text>",
        "<rect x='0' y='", c("y + 30"), "' width='", c(f"[@a] / topo * {bl}"),
        f"' height='12' rx='3' fill='{TEXTO}' fill-opacity='.2' stroke='{TEXTO}' stroke-opacity='.4'/>",
        "<rect x='0' y='", c("y + 30"), "' width='", c(f"[@c] / topo * {bl}"), f"' height='12' rx='3' fill='{VERDE}'/>",
        f"<text x='{w}' y='", c("y + 20"), f"' font-size='17' font-weight='700' fill='{TEXTO}' text-anchor='end'>",
        f("[@a]", "#,0"), "</text>",
        f"<text x='{w}' y='", c("y + 41"), f"' font-size='15' font-weight='700' fill='{VERDE}' text-anchor='end'>",
        f("[@p]", "0%"), " acerto</text>")
    corpo = junta(cab, D(f'CONCATENATEX ( r, VAR y = {hy} + ( [@k] - 1 ) * {rh:.2f} RETURN {linha}, "" )'))
    return (f'VAR t = TOPN ( {n}, FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@a", [Alertas], "@c", [Acertos],\n'
            '        "@p", [Acerto dos alertas], "@nome", CALCULATE ( MAX ( dim_linha[route_long_name] ) ) ), [@a] > 0 ),\n'
            "        [@a], DESC, dim_linha[route_id], ASC )\n"
            f'VAR r = ADDCOLUMNS ( t, "@k", {posicao("t", "@a", "dim_linha[route_id]")} )\n'
            "VAR topo = MAXX ( t, [@a] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Confianca (qualidade do dado)
# ---------------------------------------------------------------------------
def html_q_cards(w: int, h: int) -> str:
    """Tres perguntas e o veredito de cada uma: cobertura, erro de horario e feed parado."""
    pad, g = 24, 24
    cw = (w - 2 * pad - 2 * g) // 3
    ch = h - 2 * pad
    xs = [pad + i * (cw + g) for i in range(3)]
    ok = f'"{VERDE}"'
    c1 = D(f'IF ( cob >= 0.9, {ok}, "{AMBAR}" )')
    c2 = D(f'IF ( vp < 0.01, {ok}, "{AMBAR}" )')
    partes = []
    for x, perg, val, cor, l1, l2, ver, cv in [
        (xs[0], "Os ônibus aparecem no dado?", f("cob", "0.0%"), TEXTO, "das passagens viram um intervalo válido",
         D('"pior dia: " & FORMAT ( dp, "dd/mm" ) & ", com " & FORMAT ( cp, "0.0%" )'),
         D('IF ( cob >= 0.9, "✓ Sim: mais de 9 em cada 10", "⚠ Abaixo de 90%: leia com cuidado" )'), c1),
        (xs[1], "A hora estimada distorce a conta?", D('FORMAT ( [Viés de interpolação] * 60, "0.0" ) & " s"'), TEXTO,
         "a mais na espera extra, por erro de interpolação",
         D('"é " & FORMAT ( vp, "0.00%" ) & " da espera extra"'),
         D('IF ( vp < 0.01, "✓ Não: menos de 1% da espera extra", "⚠ Mais de 1% da espera extra" )'), c2),
        (xs[2], "E quando o feed da PBH para?", milhoes("[Feed parado]"), VERMELHO,
         "intervalos descartados, não estimados",
         D('FORMAT ( [Feed parado %], "0.0%" ) & " dos intervalos · " & IF ( [Dias com feed parado] = 0, '
           '"nenhuma queda nos " & FORMAT ( [Dias com qualidade], "0" ) & " dias", "queda em " '
           '& FORMAT ( [Dias com feed parado], "0" ) & " de " & FORMAT ( [Dias com qualidade], "0" ) & " dias" )'),
         D('"✓ Ficam fora da conta da espera"'), D(ok)),
    ]:
        abre = f"<text x='{x + 50}' y='{pad + ch - 36}' font-size='17' font-weight='600' font-family='{FRASE}' fill='"
        partes += [f"<rect x='{x}' y='{pad}' width='{cw}' height='{ch}' rx='18' fill='{PAINEL2}' stroke='{BORDA}'/>",
                   texto(x + 28, pad + 48, perg, 23, TEXTO, 700, fonte=FRASE),
                   f"<text x='{x + 26}' y='{pad + 132}' font-size='72' font-weight='700' fill='{cor}'>", val, "</text>",
                   texto(x + 28, pad + 172, l1, 17, SUAVE, 400, fonte=FRASE),
                   abre_texto(x + 28, pad + 199, 17, SUAVE, 400, fonte=FRASE), l2, "</text>",
                   f"<rect x='{x + 28}' y='{pad + ch - 62}' width='{cw - 56}' height='40' rx='20' fill-opacity='.14' fill='",
                   cv, "' stroke='", cv, "'/>", abre, cv, "'>", ver, "</text>"]
    return ("VAR cob = [Cobertura]\n"
            'VAR tq = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@c", [Cobertura] ), NOT ISBLANK ( [@c] ) )\n'
            "VAR pior = TOPN ( 1, tq, [@c], ASC, dim_data[data], ASC )\n"
            "VAR cp = MINX ( pior, [@c] )\nVAR dp = MAXX ( pior, dim_data[data] )\n"
            "VAR vp = [Viés de interpolação %]\n"
            f"RETURN\n    IF ( ISBLANK ( cob ), {vazio(w, h)},\n    {svg(w, h, junta(*partes))} )")


def html_q_dia(w: int, h: int) -> str:
    """Cobertura por dia (linha, eixo de 80% a 100%) e intervalos descartados com o feed parado (barras)."""
    x0, x1 = 72, w - 16
    a1, b1 = 44, 214  # faixa da cobertura
    a2, b2 = 284, 372  # faixa do feed parado
    yc = f"{b1} - ( MAX ( 0.8, MIN ( 1, [@c] ) ) - 0.8 ) / 0.2 * {b1 - a1}"
    xm = f"{x0} + INT ( dim_data[data] - d0 ) * bw + bw / 2"
    fixo = "".join([
        texto(0, 18, "COBERTURA POR DIA", 14, AZUL, 700, espaco=1.5),
        texto(200, 18, "intervalos válidos por passagem · eixo de 80% a 100%", 15, SUAVE, 400, fonte=FRASE),
        *[f"<line x1='{x0}' x2='{x1}' y1='{b1 - (v - 0.8) / 0.2 * (b1 - a1):.1f}' y2='{b1 - (v - 0.8) / 0.2 * (b1 - a1):.1f}' "
          f"stroke='{BORDA}' stroke-dasharray='4 6'/>"
          + texto(x0 - 10, round(b1 - (v - 0.8) / 0.2 * (b1 - a1) + 5), r, 14, APAGADO, 400, "end")
          for v, r in [(0.8, "80%"), (0.85, "85%"), (0.9, "90%"), (0.95, "95%"), (1.0, "100%")]],
        texto(0, a2 - 22, "INTERVALOS DESCARTADOS COM O FEED PARADO", 14, VERMELHO, 700, espaco=1.5),
        texto(440, a2 - 22, "ficam fora da conta da espera", 15, SUAVE, 400, fonte=FRASE),
        f"<line x1='{x0}' x2='{x1}' y1='{b2}' y2='{b2}' stroke='{APAGADO}'/>",
        texto(x0 - 10, b2 + 5, "0", 14, APAGADO, 400, "end"),
        f"<line x1='{x0}' x2='{x1}' y1='{a2}' y2='{a2}' stroke='{BORDA}' stroke-dasharray='4 6'/>"])
    pior = junta("<circle cx='", c(xm), "' cy='", c(yc), f"' r='7' fill='none' stroke='{VERMELHO}' stroke-width='2.5'/>",
                 "<text x='", c(f"{xm} + IF ( INT ( dim_data[data] - d0 ) * bw > {(x1 - x0) * 0.8:.0f}, -14, 14 )"),
                 "' y='", c(f"{yc} + 5"), f"' font-size='15' font-weight='700' fill='{TEXTO}' text-anchor='",
                 D(f'IF ( INT ( dim_data[data] - d0 ) * bw > {(x1 - x0) * 0.8:.0f}, "end", "start" )'), "'>pior dia: ",
                 f("[@c]", "0.0%"), " em ", D('FORMAT ( dim_data[data], "dd/mm" )'), "</text>")
    barra = junta("<rect x='", c(f"{x0} + INT ( dim_data[data] - d0 ) * bw + bw * 0.15"), "' y='", c(f"{b2} - hf"),
                  "' width='", c("bw * 0.7"), "' height='", c("hf"), f"' rx='2' fill='{VERMELHO}'/>")
    corpo = junta(
        fixo,
        f"<line x1='{x0}' x2='{x1}' y1='", c("ym"), "' y2='", c("ym"), f"' stroke='{AZUL}' stroke-opacity='.6' "
        "stroke-width='2' stroke-dasharray='8 6'/>",
        abre_texto(x1, a1 - 6, 15, AZUL, 600, "end"), "média do período: ", f("cob", "0.0%"), "</text>",
        "<polyline points='",
        D(f'CONCATENATEX ( t, FORMAT ( {xm}, "0.0", "en-US" ) & "," & FORMAT ( {yc}, "0.0", "en-US" ), " ", '
          'dim_data[data], ASC )'),
        f"' fill='none' stroke='{AZUL}' stroke-width='2.5' stroke-linejoin='round'/>",
        D('CONCATENATEX ( t, ' + junta("<circle cx='", c(xm), "' cy='", c(yc), f"' r='3.5' fill='{AZUL}'/>") + ', "" )'),
        D(f'CONCATENATEX ( pior, {pior}, "" )'),
        abre_texto(x0 - 10, a2 + 5, 14, APAGADO, 400, "end"), milhoes("ftopo"), "</text>",
        D(f'CONCATENATEX ( t, VAR hf = [@f] / ftopo * {b2 - a2} RETURN {barra}, "" )'),
        datas_eixo("t", xm, h - 22),
        abre_texto(x0, h - 2, 14, APAGADO, 400, fonte=FRASE),
        D('IF ( n <= 10, "dias do período", "datas: as segundas-feiras" )'), "</text>")
    return ('VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), "@c", [Cobertura], "@f", [Feed parado] ),\n'
            "        NOT ISBLANK ( [@c] ) )\n"
            "VAR d0 = MINX ( t, dim_data[data] )\nVAR n = INT ( MAXX ( t, dim_data[data] ) - d0 ) + 1\n"
            f"VAR bw = {x1 - x0} / n\nVAR cob = [Cobertura]\n"
            f"VAR ym = {b1} - ( MAX ( 0.8, MIN ( 1, cob ) ) - 0.8 ) / 0.2 * {b1 - a1}\n"
            "VAR fmax = MAXX ( t, [@f] )\n"
            "VAR ftopo = IF ( fmax <= 0, 1000, CEILING ( fmax * 1.1 / 10000, 1 ) * 10000 )\n"
            "VAR pior = TOPN ( 1, t, [@c], ASC, dim_data[data], ASC )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Simulador
# ---------------------------------------------------------------------------
EXPLICA_SIMULADOR = ("Como a conta funciona: tira da espera extra a parte que some quando o ônibus atrasado, que "
                     "puxou o de trás, passa no meio do caminho entre os dois (o corte sem colagem). Não inclui o 3º "
                     "ônibus em diante de um comboio.")


def html_controle(w: int, h: int) -> str:
    explica = "".join(texto(0, 600 + i * 22, linha, 15, APAGADO, 400, fonte=FRASE)
                      for i, linha in enumerate(quebrar(EXPLICA_SIMULADOR, 62, 5)) if linha)
    corpo = junta(
        abre_texto(0, 24, 16, VERDE, 700, espaco=1.5), "ESPAÇANDO ", f("[Espaçamento]", "0%"), " DOS PARES COLADOS</text>",
        texto(0, 84, "ESPERA EXTRA HOJE", 14, SUAVE, 700, espaco=1.6),
        f"<text x='-2' y='146' font-size='60' font-weight='700' fill='{AMBAR}'>+", f("ee", "0.00"),
        "<tspan font-size='26' dx='8'>min</tspan></text>",
        f"<rect x='0' y='164' width='{w}' height='18' rx='5' fill='{AMBAR}'/>",
        texto(0, 236, "COM O ESPAÇAMENTO", 14, SUAVE, 700, espaco=1.6),
        f"<text x='-2' y='298' font-size='60' font-weight='700' fill='{VERDE}'>+", f("es", "0.00"),
        "<tspan font-size='26' dx='8'>min</tspan></text>",
        "<rect x='0' y='316' width='", c(f"ws"), f"' height='18' rx='5' fill='{VERDE}'/>",
        D(f'IF ( {w} - ws > 2, ' + junta("<rect x='", c("ws + 1"), "' y='317' width='", c(f"{w} - ws - 2"),
                                          f"' height='16' rx='5' fill='none' stroke='{AMBAR}' stroke-dasharray='5 4'/>")
          + ' )'),
        texto(0, 388, "GANHO POR IDA AO PONTO", 14, SUAVE, 700, espaco=1.6),
        f"<text x='-2' y='456' font-size='64' font-weight='700' fill='{VERDE}'>", D('IF ( g > 0, "−" )'), f("g", "0.00"),
        "<tspan font-size='28' dx='8'>min</tspan></text>",
        abre_texto(0, 494, 19, TEXTO, 400, fonte=FRASE), "cerca de ", f("g * 60", "0"),
        " segundos a menos de espera</text>",
        abre_texto(0, 522, 19, SUAVE, 400, fonte=FRASE), f("[Ganho % da espera]", "0.0%"),
        " da espera média no ponto</text>",
        f"<line x1='0' x2='{w}' y1='560' y2='560' stroke='{BORDA}'/>",
        explica)
    return ("VAR ee = [Espera extra]\nVAR es = [Espera extra simulada]\nVAR g = [Ganho por passageiro]\n"
            f"VAR ws = DIVIDE ( es, ee ) * {w}\n"
            f"RETURN\n    IF ( ISBLANK ( ee ), {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_sfaixa(w: int, h: int) -> str:
    gw = w / 6
    base, top = h - 58, 52
    alto = base - top
    grupo = junta(
        "<rect x='", c("gx - 64"), "' y='", c(f"{base} - h1"), "' width='60' height='", c("h1"), f"' rx='4' fill='{AMBAR}'/>",
        "<rect x='", c("gx + 4"), "' y='", c(f"{base} - h2"), "' width='60' height='", c("h2"), f"' rx='4' fill='{VERDE}'/>",
        "<text x='", c("gx - 34"), "' y='", c(f"{base} - h1 - 9"), f"' font-size='16' font-weight='700' fill='{AMBAR}' "
        "text-anchor='middle'>", f("[@h]", "0.00"), "</text>",
        "<text x='", c("gx + 34"), "' y='", c(f"{base} - h2 - 9"), f"' font-size='16' font-weight='700' fill='{VERDE}' "
        "text-anchor='middle'>", f("[@s]", "0.00"), "</text>",
        "<text x='", c("gx"), f"' y='{base + 26}' font-size='17' fill='{TEXTO}' text-anchor='middle' font-family='{FRASE}'>",
        D("dim_faixa[faixa]"), "</text>",
        "<text x='", c("gx"), f"' y='{base + 48}' font-size='14' fill='{SUAVE}' text-anchor='middle'>",
        D("dim_faixa[horas]"), "</text>")
    corpo = junta(
        legenda(0, 18, [("q", AMBAR, "espera extra hoje (min)"), ("q", VERDE, "com o espaçamento escolhido")]),
        f"<line x1='0' x2='{w}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
        D(f'CONCATENATEX ( t, VAR gx = ( dim_faixa[ordem] - 0.5 ) * {gw:.2f} VAR h1 = [@h] / topo * {alto} '
          f'VAR h2 = [@s] / topo * {alto} RETURN {grupo}, "" )'))
    return ('VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_faixa[faixa], dim_faixa[horas], dim_faixa[ordem] ),\n'
            '        "@h", [Espera extra], "@s", [Espera extra simulada] ), NOT ISBLANK ( [@h] ) )\n'
            "VAR topo = MAXX ( t, [@h] ) * 1.05\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_ganho(w: int, h: int) -> str:
    hy, n = 30, 6
    rh = (h - hy) / n
    gx, gl = 690, 230
    cab = "".join(texto(x, 14, t, 13, SUAVE, 700, a, espaco=1.2) for x, t, a in [
        (0, "LINHA", "start"), (540, "HOJE", "end"), (650, "SIMULADA", "end"), (gx, "GANHO POR PASSAGEIRO (MIN)", "start"),
        (w, "% DO GANHO DA REDE", "end")])
    yt = f"y + {rh / 2 + 6:.1f}"
    linha = junta(
        "<text x='0' y='", c(yt), f"' font-size='18' font-weight='700' fill='{TEXTO}'>", D("dim_linha[route_id]"), "</text>",
        "<text x='80' y='", c(yt), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>", esc(corta("[@nome]", 42)),
        "</text>",
        "<text x='540' y='", c(yt), f"' font-size='17' font-weight='700' fill='{AMBAR}' text-anchor='end'>",
        f("[@h]", "0.00"), "</text>",
        "<text x='650' y='", c(yt), f"' font-size='17' font-weight='700' fill='{VERDE}' text-anchor='end'>",
        f("[@s]", "0.00"), "</text>",
        f"<rect x='{gx}' y='", c(f"y + {rh / 2 - 8:.1f}"), "' width='", c(f"[@g] / topo * {gl}"),
        f"' height='16' rx='4' fill='{VERDE}'/>",
        "<text x='", c(f"{gx + 8} + [@g] / topo * {gl}"), "' y='", c(yt),
        f"' font-size='17' font-weight='700' fill='{VERDE}'>−", f("[@g]", "0.00"), "</text>",
        f"<text x='{w}' y='", c(yt), f"' font-size='18' font-weight='700' fill='{TEXTO}' text-anchor='end'>",
        f("[@p]", "0.0%"), "</text>",
        "<line x1='0' x2='", str(w), "' y1='", c(f"y + {rh:.1f}"), "' y2='", c(f"y + {rh:.1f}"),
        f"' stroke='{BORDA}' stroke-opacity='.6'/>")
    corpo = junta(cab, D(f'CONCATENATEX ( r, VAR y = {hy} + ( [@k] - 1 ) * {rh:.2f} RETURN {linha}, "" )'))
    return (f'VAR t = TOPN ( {n}, FILTER ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@p", [Parte do ganho],\n'
            '        "@h", [Espera extra], "@s", [Espera extra simulada], "@g", [Ganho por passageiro],\n'
            '        "@nome", CALCULATE ( MAX ( dim_linha[route_long_name] ) ) ), [@p] > 0 ),\n'
            "        [@p], DESC, dim_linha[route_id], ASC )\n"
            f'VAR r = ADDCOLUMNS ( t, "@k", {posicao("t", "@p", "dim_linha[route_id]")} )\n'
            "VAR topo = MAXX ( t, [@g] )\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h, 'Com 0% de espaçamento não há ganho: escolha outro valor')},\n"
            f"    {svg(w, h, corpo)} )")


# ---------------------------------------------------------------------------
# Onde agir: recomendacoes com o numero do recorte
# ---------------------------------------------------------------------------
GRUPO_ROTA = "Da estação ao centro"  # o grupo cujas linhas aparecem listadas


def no_trajeto(medida: str) -> str:
    """Medida no grupo de trajeto da linha atual da iteracao, na rede inteira (sem o filtro de linha)."""
    return (f"VAR _tr = dim_linha[trajeto] RETURN CALCULATE ( {medida}, REMOVEFILTERS ( dim_linha ), "
            "dim_linha[trajeto] = _tr )")


def html_rotas(w: int, h: int) -> str:
    """Espera extra, colados e peso por grupo de trajeto; as linhas de maior peso do grupo da estacao ao centro."""
    bx, bl, rh, y0 = 262, 300, 82, 40
    xc, xp = 700, w
    cab = "".join(texto(x, 16, t, 13, SUAVE, 700, a, espaco=1.2) for x, t, a in [
        (0, "TRAJETO", "start"), (bx, "ESPERA EXTRA (MIN)", "start"), (xc, "COLADOS", "end"), (xp, "% DA REDE", "end")])
    grupo = junta(
        "<text x='0' y='", c("y + 30"), f"' font-size='20' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>",
        D("dim_linha[trajeto]"), "</text>",
        "<text x='0' y='", c("y + 54"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>", f("[@n]", "0"),
        " linhas · ", f("[@hp]", "0%"), " das horas</text>",
        f"<rect x='{bx}' y='", c("y + 16"), "' width='", c(f"[@e] / topo * {bl}"), f"' height='28' rx='5' fill='{AMBAR}'/>",
        "<text x='", c(f"{bx + 10} + [@e] / topo * {bl}"), "' y='", c("y + 38"),
        f"' font-size='22' font-weight='700' fill='{AMBAR}'>+", f("[@e]", "0.00"), "</text>",
        f"<text x='{xc}' y='", c("y + 38"), f"' font-size='20' font-weight='700' fill='{VERMELHO}' text-anchor='end'>",
        f("[@c]", "0.0%"), "</text>",
        f"<text x='{xp}' y='", c("y + 38"), f"' font-size='20' font-weight='700' fill='{TEXTO}' text-anchor='end'>",
        f("[@p]", "0%"), "</text>",
        "<line x1='0' x2='", str(w), "' y1='", c(f"y + {rh - 4}"), "' y2='", c(f"y + {rh - 4}"),
        f"' stroke='{BORDA}' stroke-opacity='.6'/>")
    fim = y0 + 4 * rh
    xr = f"{bx} + rede / topo * {bl}"
    yl = 446
    item = junta(
        "<text x='0' y='", c("yy"), f"' font-size='18' font-weight='700' fill='{TEXTO}'>", D("dim_linha[route_id]"),
        "</text>",
        "<text x='80' y='", c("yy"), f"' font-size='15' fill='{SUAVE}' font-family='{FRASE}'>", esc(corta("[@nome]", 50)),
        "</text>",
        f"<text x='{xc}' y='", c("yy"), f"' font-size='18' font-weight='700' fill='{AMBAR}' text-anchor='end'>+",
        f("[@e]", "0.00"), "</text>",
        f"<text x='{xp}' y='", c("yy"), f"' font-size='18' font-weight='700' fill='{VERMELHO}' text-anchor='end'>",
        f("[@c]", "0.0%"), "</text>")
    acoes = [("1", "Seccionar na estação: a linha leva o passageiro até ela e o tronco segue ao centro."),
             ("2", "Onde não der: faixa e semáforo no trecho central, e ônibus espaçados antes de entrar nele.")]
    ya = 650
    fixo = [texto(0, yl - 30, f"AS DE MAIOR PESO ENTRE AS QUE VÃO {GRUPO_ROTA.upper()}", 14,
                  SUAVE, 700, espaco=1.4),
            texto(0, ya - 30, "O QUE FAZER", 14, VERDE, 700, espaco=1.6)]
    for i, (n, frase) in enumerate(acoes):
        yy = ya + i * 32
        fixo += [f"<circle cx='11' cy='{yy - 6}' r='11' fill='{VERDE}' fill-opacity='.16' stroke='{VERDE}'/>",
                 texto(11, yy - 1, n, 14, VERDE, 700, "middle"), texto(32, yy, frase, 17, TEXTO, 400, fonte=FRASE)]
    fixo += [texto(0, h - 22, "O grupo sai do nome da linha: estação; centro, Savassi ou hospitais. É associação, não "
                   "prova de causa:", 14, APAGADO, 400, fonte=FRASE),
             texto(0, h - 2, "antes de mudar uma rota, conferir trajeto, lotação e onde o passageiro desce.", 14, APAGADO,
                   400, fonte=FRASE)]
    corpo = junta(
        cab,
        D(f'CONCATENATEX ( t, VAR y = {y0} + ( dim_linha[trajeto_ordem] - 1 ) * {rh} RETURN {grupo}, "", '
          'dim_linha[trajeto_ordem], ASC )'),
        "<line x1='", c(xr), f"' x2='", c(xr), f"' y1='{y0 + 4}' y2='{fim - 2}' stroke='{TEXTO}' stroke-opacity='.75' "
        "stroke-width='2' stroke-dasharray='6 5'/>",
        "<text x='", c(xr), f"' y='{fim + 18}' font-size='14' fill='{SUAVE}' text-anchor='middle' "
        f"font-family='{FRASE}'>rede: +", f("rede", "0.00"), "</text>",
        D(f'CONCATENATEX ( r, VAR yy = {yl} + ( [@k] - 1 ) * 34 RETURN {item}, "", [@k], ASC )'),
        "".join(fixo))
    medidas_grupo = {"@e": "[Espera extra]", "@c": "[Colados]", "@n": "[Linhas medidas]",
                     "@p": "DIVIDE ( [Volume], volrede )", "@hp": "DIVIDE ( [Horas de serviço], horasrede )"}
    cols = ",\n        ".join(f'"{k}", {no_trajeto(v)}' for k, v in medidas_grupo.items())
    rid = ("VAR _rid = dim_linha[route_id] RETURN CALCULATE ( {m}, REMOVEFILTERS ( dim_linha ), "
           "dim_linha[route_id] = _rid )")
    return ("VAR rede = [Espera extra da rede no recorte]\nVAR volrede = [Volume da rede]\n"
            "VAR horasrede = CALCULATE ( [Horas de serviço], REMOVEFILTERS ( dim_linha ) )\n"
            "VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_linha[trajeto], dim_linha[trajeto_ordem] ),\n        "
            f"{cols} ),\n    NOT ISBLANK ( [@e] ) )\n"
            "VAR topo = MAX ( MAXX ( t, [@e] ), rede ) * 1.12\n"
            f"VAR l = CALCULATETABLE ( VALUES ( dim_linha[route_id] ), REMOVEFILTERS ( dim_linha ), "
            f"dim_linha[trajeto] = {lit(GRUPO_ROTA)} )\n"
            f'VAR l2 = FILTER ( ADDCOLUMNS ( l, "@v", {rid.format(m="[Volume]")},\n'
            f'        "@e", {rid.format(m="[Espera extra]")},\n        "@c", {rid.format(m="[Colados]")},\n'
            f'        "@nome", {rid.format(m="MAX ( dim_linha[route_long_name] )")} ), NOT ISBLANK ( [@v] ) )\n'
            "VAR top5 = TOPN ( 5, l2, [@v], DESC, dim_linha[route_id], ASC )\n"
            f'VAR r = ADDCOLUMNS ( top5, "@k", {posicao("top5", "@v", "dim_linha[route_id]")} )\n'
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_operacao(w: int, h: int) -> str:
    """Cinco ajustes na circulacao, cada um com o numero do recorte que o sustenta."""
    rh = h / 5
    xt = 236

    def linha(i: int, valor: list, sub: list, cor_: str, titulo: list, l1: list, l2: str) -> list:
        y = round(i * rh)
        partes = [f"<text x='0' y='{y + 46}' font-size='40' font-weight='700' fill='{cor_}'>", *valor, "</text>",
                  abre_texto(1, y + 70, 14, SUAVE, 400, fonte=FRASE), *sub, "</text>",
                  abre_texto(xt, y + 28, 19, TEXTO, 600, fonte=FRASE), *titulo, "</text>",
                  abre_texto(xt, y + 52, 16, SUAVE, 400, fonte=FRASE), *l1, "</text>",
                  texto(xt, y + 74, l2, 16, APAGADO, 400, fonte=FRASE)]
        if i < 4:
            partes.append(f"<line x1='0' x2='{w}' y1='{y + rh - 3:.0f}' y2='{y + rh - 3:.0f}' stroke='{BORDA}' "
                          "stroke-opacity='.7'/>")
        return partes

    un = lambda t: f"<tspan font-size='20' dx='6'>{t}</tspan>"  # noqa: E731
    partes = (
        linha(0, ["−", f("[Ganho sem colagem]", "0.00"), un("min")], ["por ida ao ponto"], VERDE,
              ["Espaçar os ônibus colados no caminho"],
              ["Segurar o que encostou no da frente: some ", f("[Corte sem colagem]", "0%"), " da espera extra."],
              "Controle por GPS no ponto. É o Simulador com 100% dos pares.")
        + linha(1, [f("[Linhas para 80%]", "0"), un("linhas")], ["de ", f("[Linhas na rede]", "0"), " medidas"], AMBAR,
                ["Começar por poucas linhas"], ["Elas somam 80% da espera extra do recorte."],
                "O mesmo esforço de controle alcança mais gente nelas.")
        + linha(2, ["+", f("[@x]", "0.00"), un("min")], [D("faixa_max")], AMBAR,
                ["Reforçar o controle no ", D("LOWER ( faixa_max )")],
                ["A maior espera extra entre as faixas de mais serviço (+", f("[@y]", "0.00"), " no ",
                 D("LOWER ( faixa_min )"), ")."],
                "Fiscal e regulação onde a irregularidade é maior por passageiro.")
        + linha(3, [f("[Colados atrás de colado %]", "0%")], ["dos colados"], VERMELHO,
                ["Despachar com intervalo fixo no terminal"],
                ["São comboios de 3 ou mais ônibus, que espaçar no caminho não desfaz."],
                "O controle começa na saída do terminal, não só no trajeto.")
        + linha(4, [f("[Vezes a chance]", "0.0"), un("×")], ["a chance sem modelo"], VERDE,
                ["Usar a previsão como lista de prioridade"],
                ["Dez paradas antes, os alertas do modelo acertam ", f("[Acerto dos alertas]", "0%"), "."],
                "Mostrar ao controle os de maior risco, sem ação automática.")
    )
    # as variaveis da faixa vem de uma linha so: [@x] e [@y] sao as esperas da pior e da melhor faixa
    corpo = junta(*partes)
    return ('VAR tf = ADDCOLUMNS ( ALL ( dim_faixa[faixa], dim_faixa[ordem] ), "@x", [Espera extra], '
            '"@h", [Horas de serviço] )\n'
            "VAR htot = SUMX ( tf, [@h] )\n"
            "VAR mov = FILTER ( tf, NOT ISBLANK ( [@x] ) && DIVIDE ( [@h], htot ) >= 0.10 )\n"
            "VAR pior = TOPN ( 1, mov, [@x], DESC, dim_faixa[ordem], ASC )\n"
            "VAR melhor = TOPN ( 1, mov, [@x], ASC, dim_faixa[ordem], ASC )\n"
            "VAR faixa_max = MAXX ( pior, dim_faixa[faixa] )\nVAR faixa_min = MAXX ( melhor, dim_faixa[faixa] )\n"
            'VAR um = ROW ( "@x", MAXX ( pior, [@x] ), "@y", MAXX ( melhor, [@x] ) )\n'
            f"RETURN\n    IF ( ISBLANK ( [Espera extra] ) || COUNTROWS ( mov ) = 0, {vazio(w, h)},\n"
            f'    CONCATENATEX ( um, {svg(w, h, corpo)}, "" ) )')


VIAS = [("Waldyr Soeiro Emrich", "Av. Waldyr Soeiro Emrich"), ("Cristiano Machado", "Av. Cristiano Machado"),
        ("Raja Gabaglia", "Av. Raja Gabaglia"), ("Ursula Paulino", "R. Úrsula Paulino"),
        ("Nossa Senhora do Carmo", "Av. N. Sra. do Carmo"), ("Amazonas", "Av. Amazonas"),
        ("Dom Pedro II", "Av. Dom Pedro II"), ("Afonso Pena", "Av. Afonso Pena"),
        ("Carlos Luz", "Av. Pres. Carlos Luz"), ("Antonio Carlos", "Av. Pres. Antônio Carlos"),
        ("Contorno", "Av. do Contorno")]
TOP_VIAS = 5


def html_corredores(w: int, h: int) -> str:
    """As avenidas de maior espera extra media nos pontos (ultimos 28 dias), contra a media da rede."""
    rh = h / TOP_VIAS
    bx, bl, xc = 300, 330, w
    yt = f"y + {rh / 2 + 6:.1f}"
    item = junta(
        "<text x='0' y='", c(yt), f"' font-size='18' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>",
        D("[rot]"), "</text>",
        f"<rect x='{bx}' y='", c(f"y + {rh / 2 - 10:.1f}"), "' width='", c(f"[@e] / topo * {bl}"),
        f"' height='20' rx='4' fill='{AMBAR}'/>",
        "<text x='", c(f"{bx + 10} + [@e] / topo * {bl}"), "' y='", c(yt),
        f"' font-size='19' font-weight='700' fill='{AMBAR}'>+", f("[@e]", "0.00"), "</text>",
        f"<text x='{xc}' y='", c(yt), f"' font-size='17' fill='{SUAVE}' text-anchor='end' font-family='{FRASE}'>"
        f"<tspan font-weight='700' fill='{VERMELHO}'>", f("[@c]", "0%"), "</tspan> colados</text>")
    xr = f"{bx} + rede / topo * {bl}"
    corpo = junta(
        D(f'CONCATENATEX ( r, VAR y = ( [@k] - 1 ) * {rh:.2f} RETURN {item}, "", [@k], ASC )'),
        "<line x1='", c(xr), "' x2='", c(xr), f"' y1='2' y2='{h - 2}' stroke='{TEXTO}' stroke-opacity='.75' "
        "stroke-width='2' stroke-dasharray='6 5'/>")
    linhas = ",\n        ".join(f"{{ {lit(k)}, {lit(rot)} }}" for k, rot in VIAS)
    no_via = ("VAR _via = [k] RETURN CALCULATE ( {m}, FILTER ( ALL ( fato_paradas[stop_name] ), "
              "CONTAINSSTRING ( fato_paradas[stop_name], _via ) ) )")
    return (f'VAR vias = DATATABLE ( "k", STRING, "rot", STRING, {{\n        {linhas} }} )\n'
            f'VAR t = FILTER ( ADDCOLUMNS ( vias, "@e", {no_via.format(m="[Ponto · espera extra]")},\n'
            f'        "@c", {no_via.format(m="[Ponto · colados]")},\n'
            f'        "@h", {no_via.format(m="[Ponto · horas]")} ), [@h] >= 5000 )\n'
            f"VAR tp = TOPN ( {TOP_VIAS}, t, [@e], DESC, [k], ASC )\n"
            f'VAR r = ADDCOLUMNS ( tp, "@k", {posicao("tp", "@e", "[k]")} )\n'
            "VAR rede = [Ponto · espera extra]\n"
            "VAR topo = MAX ( MAXX ( tp, [@e] ), rede ) * 1.15\n"
            f"RETURN\n    IF ( COUNTROWS ( tp ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


PARTE_MIN_LINHA = 0.001  # linha entra na dispersao com 0,1% ou mais das horas (a analise usou 2.000 h de 1,75 mi)


def correlacao(nome: str, x: str, y: str) -> str:
    """Correlacao de Pearson entre duas colunas da tabela t (n linhas), como VAR DAX."""
    return (f"VAR {nome}_x = SUMX ( t, {x} ) VAR {nome}_y = SUMX ( t, {y} )\n"
            f"VAR {nome}_xy = SUMX ( t, {x} * {y} ) VAR {nome}_xx = SUMX ( t, {x} ^ 2 ) "
            f"VAR {nome}_yy = SUMX ( t, {y} ^ 2 )\n"
            f"VAR {nome} = DIVIDE ( n * {nome}_xy - {nome}_x * {nome}_y,\n"
            f"    SQRT ( ( n * {nome}_xx - {nome}_x ^ 2 ) * ( n * {nome}_yy - {nome}_y ^ 2 ) ) )\n")


def html_porque_linhas(w: int, h: int) -> str:
    """Duas dispersoes por linha: espera regular (intervalo) e colados contra espera extra, com a correlacao."""
    gap = 90
    larg_g = (w - 60 - gap) // 2
    top, base = 74, h - 46
    alto = base - top

    def forca(r: str) -> str:
        return (f'SWITCH ( TRUE (), ABS ( {r} ) < 0.2, "quase nenhuma relação", ABS ( {r} ) < 0.5, "relação fraca", '
                f'ABS ( {r} ) < 0.7, "relação média", "relação forte" )')

    def grafico(x0: int, col: str, mx: str, r: str, cor_: str, eixo: str, fmt_max: str, rotulo: str) -> list:
        x1 = x0 + larg_g
        bolha = junta("<circle cx='", c(f"{x0} + MIN ( {col} / {mx}, 1 ) * {larg_g}"), "' cy='",
                      c(f"{base} - MIN ( [@e] / my, 1 ) * {alto}"), "' r='", c("2.5 + 8 * SQRT ( DIVIDE ( [@h], mh ) )"),
                      f"' fill='{cor_}' fill-opacity='.55' stroke='{FUNDO}' stroke-width='.8'/>")
        return [
            texto(x0, 22, rotulo, 14, SUAVE, 700, espaco=1.4),
            f"<text x='{x0}' y='60' font-size='34' font-weight='700' fill='{cor_}'>r = ", f(r, "0.00"), "</text>",
            f"<text x='{x0 + 170}' y='58' font-size='18' fill='{TEXTO}' font-family='{FRASE}'>", D(forca(r)), "</text>",
            f"<line x1='{x0}' x2='{x1}' y1='{base}' y2='{base}' stroke='{APAGADO}'/>",
            f"<line x1='{x0}' x2='{x0}' y1='{top}' y2='{base}' stroke='{APAGADO}'/>",
            D(f'CONCATENATEX ( t, {bolha}, "", [@h], DESC )'),
            texto(x0, base + 20, "0", 14, APAGADO, 400, "middle"),
            f"<text x='{x1}' y='{base + 20}' font-size='14' fill='{APAGADO}' text-anchor='end'>", f(mx, fmt_max),
            "</text>",
            texto((x0 + x1) // 2, h - 2, eixo, 15, SUAVE, 400, "middle", FRASE),
            texto(x0 - 8, base + 5, "0", 14, APAGADO, 400, "end"),
            f"<text x='{x0 - 8}' y='{top + 5}' font-size='14' fill='{APAGADO}' text-anchor='end'>", f("my", "0"),
            "</text>"]

    xa, xb = 60, 60 + larg_g + gap
    corpo = junta(
        *grafico(xa, "[@r]", "mr", "r_int", APAGADO, "espera com ônibus regulares (metade do intervalo, min)", "0",
                 "INTERVALO ENTRE ÔNIBUS"),
        *grafico(xb, "[@c]", "mc", "r_col", VERMELHO, "intervalos colados", "0%", "ÔNIBUS COLADOS"),
        f"<text transform='translate(14,{(top + base) // 2}) rotate(-90)' font-size='15' fill='{SUAVE}' "
        f"text-anchor='middle' font-family='{FRASE}'>espera extra (min)</text>")
    # so alta frequencia: na baixa o passageiro consulta o horario e a espera extra nao representa ninguem
    return ('VAR t0 = CALCULATETABLE ( ADDCOLUMNS ( VALUES ( dim_linha[route_id] ), "@r", [Espera regular],\n'
            '        "@c", [Colados], "@e", [Espera extra], "@h", [Horas de serviço] ),\n'
            '    REMOVEFILTERS ( dim_frequencia ), dim_frequencia[frequencia] = "alta" )\n'
            "VAR htot = SUMX ( t0, [@h] )\n"
            f"VAR t = FILTER ( t0, NOT ISBLANK ( [@e] ) && DIVIDE ( [@h], htot ) >= {PARTE_MIN_LINHA} )\n"
            "VAR n = COUNTROWS ( t )\n"
            + correlacao("r_int", "[@r]", "[@e]") + correlacao("r_col", "[@c]", "[@e]")
            + "VAR mr = PERCENTILEX.INC ( t, [@r], 0.98 ) * 1.1\nVAR mc = PERCENTILEX.INC ( t, [@c], 0.98 ) * 1.1\n"
            "VAR my = PERCENTILEX.INC ( t, [@e], 0.98 ) * 1.15\nVAR mh = MAXX ( t, [@h] )\n"
            f"RETURN\n    IF ( n < 5, {vazio(w, h, 'Poucas linhas no recorte escolhido')},\n    {svg(w, h, corpo)} )")


FAIXAS_LINHAS = [("1 linha", 1, 1), ("2 a 3 linhas", 2, 3), ("4 a 8 linhas", 4, 8), ("9 ou mais", 9, 999)]


def html_porque_pontos(w: int, h: int) -> str:
    """Espera extra nos pontos agrupados pelo numero de linhas que passam neles (ultimos 28 dias)."""
    rodape = 60
    rh = (h - rodape) / len(FAIXAS_LINHAS)
    bx, bl = 190, w - 190 - 90
    yt = f"y + {rh / 2:.1f}"
    item = junta(
        "<text x='0' y='", c(f"{yt} - 2"), f"' font-size='19' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>",
        D("[rot]"), "</text>",
        "<text x='0' y='", c(f"{yt} + 22"), f"' font-size='14' fill='{SUAVE}' font-family='{FRASE}'>",
        f("[@n]", "#,0"), " pontos</text>",
        f"<rect x='{bx}' y='", c(f"{yt} - 14"), "' width='", c(f"[@e] / topo * {bl}"),
        f"' height='24' rx='4' fill='{AMBAR}'/>",
        "<text x='", c(f"{bx + 10} + [@e] / topo * {bl}"), "' y='", c(f"{yt} + 6"),
        f"' font-size='20' font-weight='700' fill='{AMBAR}'>+", f("[@e]", "0.00"), "</text>")
    xr = f"{bx} + rede / topo * {bl}"
    fim = h - rodape
    corpo = junta(
        D(f'CONCATENATEX ( t, VAR y = ( [o] - 1 ) * {rh:.2f} RETURN {item}, "", [o], ASC )'),
        "<line x1='", c(xr), "' x2='", c(xr), f"' y1='4' y2='{fim - 4}' stroke='{TEXTO}' stroke-opacity='.75' "
        "stroke-width='2' stroke-dasharray='6 5'/>",
        "<text x='", c(xr), f"' y='{fim + 16}' font-size='14' fill='{SUAVE}' text-anchor='middle' "
        f"font-family='{FRASE}'>todos: +", f("rede", "0.00"), "</text>",
        texto(0, h - 4, "A irregularidade vem da linha: o ponto só junta as linhas que passam nele.", 15, APAGADO, 400,
              fonte=FRASE))
    linhas = ",\n        ".join(f"{{ {lit(rot)}, {lo}, {hi}, {i} }}" for i, (rot, lo, hi) in enumerate(FAIXAS_LINHAS, 1))
    na_faixa = ("VAR _lo = [lo] VAR _hi = [hi] RETURN CALCULATE ( {m}, FILTER ( ALL ( fato_paradas[linhas] ), "
                "fato_paradas[linhas] >= _lo && fato_paradas[linhas] <= _hi ) )")
    return (f'VAR faixas = DATATABLE ( "rot", STRING, "lo", INTEGER, "hi", INTEGER, "o", INTEGER, {{\n        {linhas} }} )\n'
            f'VAR t = FILTER ( ADDCOLUMNS ( faixas, "@e", {na_faixa.format(m="[Ponto · espera extra]")},\n'
            f'        "@n", {na_faixa.format(m="DISTINCTCOUNT ( fato_paradas[stop_id] )")} ), NOT ISBLANK ( [@e] ) )\n'
            "VAR rede = [Ponto · espera extra]\n"
            "VAR topo = MAX ( MAXX ( t, [@e] ), rede ) * 1.18\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


def html_porque_dias(w: int, h: int) -> str:
    """Espera extra por tipo de dia (ignora o filtro de tipo de dia) e a parte das horas de servico."""
    rh = (h - 20) / 3
    bx, bl, xh = 250, w - 250 - 300, w
    yt = f"y + {rh / 2 + 7:.1f}"
    item = junta(
        "<text x='0' y='", c(yt), f"' font-size='19' font-weight='600' fill='{TEXTO}' font-family='{FRASE}'>",
        D("dim_tipo_dia[tipo]"), "</text>",
        f"<rect x='{bx}' y='", c(f"y + {rh / 2 - 11:.1f}"), "' width='", c(f"[@e] / topo * {bl}"),
        f"' height='22' rx='4' fill='{AMBAR}'/>",
        "<text x='", c(f"{bx + 10} + [@e] / topo * {bl}"), "' y='", c(yt),
        f"' font-size='20' font-weight='700' fill='{AMBAR}'>+", f("[@e]", "0.00"), "</text>",
        f"<text x='{xh}' y='", c(yt), f"' font-size='17' fill='{SUAVE}' text-anchor='end' font-family='{FRASE}'>"
        f"<tspan font-weight='700' fill='{TEXTO}'>", f("DIVIDE ( [@h], htot )", "0.0%"), "</tspan> das horas · ",
        f"<tspan font-weight='700' fill='{VERMELHO}'>", f("[@c]", "0%"), "</tspan> colados</text>")
    xr = f"{bx} + rede / topo * {bl}"
    corpo = junta(
        D(f'CONCATENATEX ( t, VAR y = ( dim_tipo_dia[ordem] - 1 ) * {rh:.2f} RETURN {item}, "", dim_tipo_dia[ordem], ASC )'),
        "<line x1='", c(xr), "' x2='", c(xr), f"' y1='2' y2='{h - 22}' stroke='{TEXTO}' stroke-opacity='.75' "
        "stroke-width='2' stroke-dasharray='6 5'/>",
        "<text x='", c(xr), f"' y='{h - 2}' font-size='14' fill='{SUAVE}' text-anchor='middle' "
        f"font-family='{FRASE}'>todos os dias: +", f("rede", "0.00"), "</text>")
    return ('VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_tipo_dia[tipo], dim_tipo_dia[ordem] ), "@e", [Espera extra],\n'
            '        "@c", [Colados], "@h", [Horas de serviço] ), NOT ISBLANK ( [@e] ) )\n'
            "VAR htot = SUMX ( t, [@h] )\n"
            "VAR rede = CALCULATE ( [Espera extra], REMOVEFILTERS ( dim_tipo_dia ) )\n"
            "VAR topo = MAX ( MAXX ( t, [@e] ), rede ) * 1.18\n"
            f"RETURN\n    IF ( COUNTROWS ( t ) = 0, {vazio(w, h)},\n    {svg(w, h, corpo)} )")


LEITURAS = [("Controlar o espaçamento, não só a frota", "Mais ônibus numa linha irregular não a deixa regular."),
            ("Agir linha a linha, não ponto a ponto", "Ponto com muitas linhas não espera mais que os outros."),
            ("Ver o fim de semana à parte", "Roda pouca linha frequente: pesa pouco na média da rede.")]


def html_porque_leitura(w: int, h: int) -> str:
    """Tres leituras fixas do que a pagina mostra (texto, sem numero calculado)."""
    rh = h / len(LEITURAS)
    partes = []
    for i, (titulo, frase) in enumerate(LEITURAS):
        y = round(i * rh)
        partes += [f"<circle cx='14' cy='{y + 22}' r='14' fill='{VERDE}' fill-opacity='.16' stroke='{VERDE}'/>",
                   texto(14, y + 28, str(i + 1), 16, VERDE, 700, "middle"),
                   texto(42, y + 28, titulo, 19, TEXTO, 600, fonte=FRASE),
                   texto(42, y + 54, frase, 16, SUAVE, 400, fonte=FRASE)]
    return svg(w, h, junta(*partes))


# ---------------------------------------------------------------------------
# Registro: (pagina, painel) -> (medida, funcao, doc). O relatorio poe o visual na area do painel.
# ---------------------------------------------------------------------------
PAINEIS = {
    ("visao", "hero"): ("HTML capa", html_capa, "Capa da visao geral: espera extra, frase, variacao e ilustracao."),
    ("visao", "numeros"): ("HTML números", html_numeros, "Azulejos com o tamanho da medicao."),
    ("visao", "dia"): ("HTML dia a dia", html_dia, "Espera extra por dia, media do periodo e eventos numerados."),
    ("visao", "faixa"): ("HTML faixa", html_faixa, "Espera regular e extra por faixa horaria."),
    ("onde", "calor"): ("HTML calor linha faixa", html_calor, "As 30 linhas de maior volume x faixa horaria."),
    ("onde", "calendario"): ("HTML calendário", html_calendario, "Espera extra dia a dia em semanas, com eventos."),
    ("onde", "semana"): ("HTML semana faixa", html_semana, "Espera extra por dia da semana e faixa horaria."),
    ("linhas", "pareto"): ("HTML concentração", html_pareto, "Linhas que somam 80% e a curva acumulada."),
    ("linhas", "quadrantes"): ("HTML quadrantes", html_quadrantes, "Colados contra espera extra por linha."),
    ("linhas", "ranking"): ("HTML ranking", html_ranking, "As 7 linhas de maior volume, com tendencia."),
    ("pontos", "mapa"): ("HTML mapa", html_mapa, "Pontos de maior volume no mapa, os 10 piores numerados."),
    ("pontos", "pnumeros"): ("HTML pontos números", html_pnumeros, "Numeros dos pontos do mapa."),
    ("pontos", "piores"): ("HTML piores pontos", html_piores, "Os 10 pontos de maior volume."),
    ("colados", "cnum"): ("HTML colados números", html_cnum, "Colados, abaixo de 60 s, comboios e corte."),
    ("colados", "hist"): ("HTML histograma", html_hist, "Histograma do intervalo dividido pelo medio."),
    ("colados", "cfaixa"): ("HTML colados faixa", html_cfaixa, "Colados por faixa horaria."),
    ("colados", "clinhas"): ("HTML colados linhas", html_clinhas, "Linhas com mais intervalos colados."),
    ("previsao", "pv_capa"): ("HTML previsão capa", html_pv_capa, "Acerto dos alertas contra a chance sem modelo."),
    ("previsao", "pv_num"): ("HTML previsão números", html_pv_num, "Alertas, acertos, colados avisados e passagens."),
    ("previsao", "pv_dia"): ("HTML previsão dia", html_pv_dia, "Alertas e acertos por dia do teste."),
    ("previsao", "pv_linhas"): ("HTML previsão linhas", html_pv_linhas, "Linhas com mais alertas no teste."),
    ("qualidade", "q_cards"): ("HTML confiança", html_q_cards, "Cobertura, vies de interpolacao e feed parado."),
    ("qualidade", "q_dia"): ("HTML confiança dia", html_q_dia, "Cobertura e feed parado por dia."),
    ("simulador", "controle"): ("HTML simulador", html_controle, "Espera extra hoje, simulada e o ganho."),
    ("simulador", "sfaixa"): ("HTML simulador faixa", html_sfaixa, "Espera extra hoje e simulada por faixa."),
    ("simulador", "ganho"): ("HTML simulador linhas", html_ganho, "Linhas com maior parte do ganho."),
    ("ficha", "ffaixa"): ("HTML ficha faixa", html_faixa, "Espera regular e extra por faixa, da linha escolhida."),
    ("ficha", "fdia"): ("HTML ficha dia", html_dia, "Espera extra por dia da linha escolhida, com eventos."),
    ("porque", "plinhas"): ("HTML o que pesa linhas", html_porque_linhas,
                            "Intervalo e colados contra espera extra por linha, com a correlacao."),
    ("porque", "ppontos"): ("HTML o que pesa pontos", html_porque_pontos,
                            "Espera extra nos pontos pelo numero de linhas."),
    ("porque", "pdias"): ("HTML o que pesa dias", html_porque_dias, "Espera extra por tipo de dia."),
    ("porque", "pleitura"): ("HTML o que pesa leitura", html_porque_leitura, "Tres leituras do que a pagina mostra."),
    ("acoes", "rotas"): ("HTML onde agir rotas", html_rotas, "Espera extra por grupo de trajeto e as linhas do grupo."),
    ("acoes", "operacao"): ("HTML onde agir operação", html_operacao, "Cinco ajustes na circulacao, com o numero."),
    ("acoes", "corredores"): ("HTML onde agir corredores", html_corredores, "Avenidas de maior espera extra nos pontos."),
}


SEM_FUNDO = {("pontos", "mapa")}  # os pontos da cidade estao na arte, por baixo do mapa


def fundo(p) -> str:
    """Fundo do envelope do HTML, igual ao da arte por baixo.

    No relatorio nao muda nada (cobre a arte com a mesma cor). No modo foco o visual aparece
    sozinho, sem a arte: sem fundo proprio ele ficava branco.
    """
    if p.titulo:  # so o miolo: abaixo do titulo o degrade da arte ja chegou ao PAINEL
        return f"background:{PAINEL}"
    acc = p.cor  # painel sem titulo: o HTML cobre o painel inteiro, copia a moldura da arte
    return (f"box-sizing:border-box;border-radius:24px;"
            f"border:1px solid color-mix(in srgb, {acc} 16%, rgba(148,163,255,.10));"
            f"background:linear-gradient(180deg, color-mix(in srgb, {acc} 8%, {PAINEL}), {PAINEL} 110px);"
            f"box-shadow:inset 0 1px 0 color-mix(in srgb, {acc} 30%, transparent)")


def medidas_html() -> list[tuple]:
    from relatorio import POR_CHAVE, area_html  # o layout mora no relatorio

    saida = []
    for (pag, painel), (nome, fn, doc) in PAINEIS.items():
        p = POR_CHAVE[pag].p(painel)
        _, _, w, h = area_html(p)
        expr = fn(w, h)
        if (pag, painel) not in SEM_FUNDO:
            estilo = fundo(p)
            expr = (expr.replace("<div style='width:100%;height:100%;overflow:hidden'>",
                                 f"<div style='width:100%;height:100%;overflow:hidden;{estilo}'>")
                    .replace("<div style='width:100%;height:100%'>", f"<div style='width:100%;height:100%;{estilo}'>"))
        saida.append((nome, expr, None, "HTML", doc, {}))
    return saida
