"""Relatorio do Power BI (PBIR): paginas, layout dos paineis e tema.

O desenho fixo fica na arte de fundo (arte.py): menu lateral, letreiro, titulos e
molduras dos paineis. Por cima, cada painel tem um visual HTML Content com uma
medida de paineis.py (SVG montado em DAX). Nativos so os filtros do cabecalho, o
menu (navegador invisivel sobre a arte), o selo da carga e o seletor do simulador.
O layout de cada painel esta aqui (PAGINAS) e a arte le daqui, para a moldura e o
visual nunca se desencontrarem.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from modelo import AMBAR, AZUL, BORDA, FUNDO, NS, PAINEL, PAINEL2, SUAVE, APAGADO, TEXTO, TOP_CALOR, VERDE, VERMELHO

W, H = 1920, 1080
TRILHO = 104  # largura do menu lateral desenhado na arte
NAV_TOPO, NAV_ITEM = 168, 80  # primeiro item do menu e altura de cada um (11 paginas ate 1048)
FONTE = "Segoe UI"
FONTE_FORTE = "Segoe UI Semibold"
HTML_VISUAL = "htmlContent443BE3AD55E043BF878BED274D3A6865"  # HTML Content (AppSource, certificado)
CARROSSEL = "radarCarrossel02E4BDFE01EB4C8F9F3046BF8481C8FF"  # visual proprio (powerbi/carrossel), vai dentro do PBIP
# Papel do carrossel -> medida (a linha vem de dim_linha[route_id])
CARROSSEL_PAPEIS = [("nome", "Nome da linha"), ("espera", "Espera média"), ("extra", "Espera extra"),
                    ("colados", "Colados"), ("corte", "Corte sem colagem"), ("parte", "Parte da espera extra"),
                    ("posicao", "Posição"), ("volume", "Volume"), ("tendencia", "Carrossel tendência"),
                    ("rede", "Carrossel rede")]

# Filtros do cabecalho: (chave, tabela, coluna, rotulo, x, largura, padrao, unico, busca)
FILTROS = [
    ("periodo", "sel_periodo", "periodo", "PERÍODO", 1060, 200, "Últimos 28 dias", True, False),
    ("tipo", "dim_tipo_dia", "tipo", "TIPO DE DIA", 1272, 190, None, False, False),
    ("freq", "dim_frequencia", "frequencia_rotulo", "FREQUÊNCIA", 1474, 190, None, False, False),
    ("linha", "dim_linha", "rotulo", "LINHA", 1676, 212, None, False, True),
]
FILTRO_Y, FILTRO_H = 52, 46


def nome_visual(chave: str) -> str:
    return uuid.uuid5(NS, "visual/" + chave).hex[:20]


def nome_pagina(chave: str) -> str:
    return uuid.uuid5(NS, "pagina/" + chave).hex[:20]


# ---------------------------------------------------------------------------
# Layout: paginas e paineis (a arte desenha a moldura, o HTML ocupa o miolo)
# ---------------------------------------------------------------------------
@dataclass
class Painel:
    chave: str
    x: int
    y: int
    w: int
    h: int
    num: str = ""
    olho: str = ""
    titulo: str = ""
    nota: str = ""
    cor: str = AMBAR
    html_topo: int = 0  # espaco no alto do miolo para um visual nativo (seletor do simulador)

    @property
    def topo(self) -> int:
        """Altura do cabecalho do painel (numero, olho, titulo e nota)."""
        if not self.titulo:
            return 24
        return 118 if self.nota else 92

    def miolo(self, margem: int = 26) -> tuple[int, int, int, int]:
        return self.x + margem, self.y + self.topo, self.w - 2 * margem, self.h - self.topo - 20


@dataclass
class Pag:
    chave: str
    nome: str
    titulo: str
    destaque: str
    olho: str
    icone: str
    paineis: list[Painel] = field(default_factory=list)
    largura: int = W
    altura: int = H

    def p(self, chave: str) -> Painel:
        return next(x for x in self.paineis if x.chave == chave)


PAGINAS = [
    Pag("visao", "Visão geral", "Visão", "geral", "A ESPERA NO PONTO", "visao", [
        Painel("hero", 136, 148, 1100, 400, cor=AMBAR),
        Painel("numeros", 1252, 148, 636, 400, "02", "NÚMEROS DO RECORTE", "O tamanho da medição", cor=AZUL),
        Painel("dia", 136, 564, 1100, 492, "03", "DIA A DIA", "Espera extra por dia",
               "Minutos a mais por ida ao ponto · barra clara: dia com evento na cidade, numerado na lista", AMBAR),
        Painel("faixa", 1252, 564, 636, 492, "04", "HORA DO DIA", "Espera por faixa horária",
               "Azul: com intervalos iguais · âmbar: a espera extra", AZUL),
    ]),
    Pag("onde", "Onde e quando", "Onde e", "quando", "LINHA, FAIXA E DIA", "onde", [
        Painel("calor", 136, 148, 1000, 908, "01", "LINHA × FAIXA", f"As {TOP_CALOR} linhas que mais pesam",
               "Espera extra (min) por faixa · as de maior volume no recorte, da maior espera extra para a menor", AMBAR),
        Painel("calendario", 1152, 148, 736, 520, "02", "CALENDÁRIO", "Espera extra dia a dia",
               "Ponto branco: dia com evento na cidade · passe o mouse para ver o motivo", AMBAR),
        Painel("semana", 1152, 684, 736, 372, "03", "SEMANA × FAIXA", "Dia da semana e hora", "", AMBAR),
    ]),
    Pag("linhas", "Linhas", "Linhas", "", "QUEM CONCENTRA A ESPERA", "linhas", [
        Painel("pareto", 136, 148, 1752, 420, "01", "CONCENTRAÇÃO", "Poucas linhas, muita espera",
               "Volume: espera extra × horas de serviço da linha · mede o peso dela na espera da rede", AMBAR),
        Painel("quadrantes", 136, 584, 860, 472, "02", "QUADRANTES", "Colados contra espera extra",
               "Cada bolha é uma linha (tamanho: horas de serviço) · tracejado: a rede", VERMELHO),
        Painel("ranking", 1012, 584, 876, 472, "03", "RANKING", "Onde está a espera extra",
               "As 7 de maior volume · para ver uma linha a fundo, escolha no filtro LINHA e abra a Ficha", AMBAR),
    ]),
    Pag("pontos", "Pontos", "Pontos", "", "ÚLTIMOS 28 DIAS", "pontos", [
        Painel("mapa", 136, 148, 700, 908, "01", "MAPA", "Espera extra por ponto",
               "Janela fixa dos últimos 28 dias: não segue o período nem a linha", AMBAR),
        Painel("pnumeros", 852, 148, 1036, 200, "02", "OS PONTOS", "O que o mapa mostra", "", AMBAR),
        Painel("piores", 852, 364, 1036, 692, "03", "PIORES PONTOS", "Onde mais se espera a mais",
               "Ordem pelo volume (espera extra × horas de serviço no ponto) · o número é o mesmo do mapa", AMBAR),
    ]),
    Pag("colados", "Colados", "Ônibus", "colados", "DOIS DA MESMA LINHA QUASE JUNTOS", "colados", [
        Painel("cnum", 136, 148, 1752, 190, cor=VERMELHO),
        Painel("hist", 136, 354, 1100, 702, "02", "DISTRIBUIÇÃO", "Como os intervalos se espalham",
               "Parte dos intervalos em cada tamanho · rede inteira: não segue o filtro de linha", VERMELHO),
        Painel("cfaixa", 1252, 354, 636, 330, "03", "HORA DO DIA", "Colados por faixa horária", "", VERMELHO),
        Painel("clinhas", 1252, 700, 636, 356, "04", "LINHAS", "Onde mais se cola",
               "Intervalos colados no recorte · % dos intervalos da linha", VERMELHO),
    ]),
    Pag("previsao", "Previsão", "Prever os", "colados", "O MODELO DA FASE 5", "previsao", [
        Painel("pv_capa", 136, 148, 1100, 420, cor=VERDE),
        Painel("pv_num", 1252, 148, 636, 420, "02", "O TESTE", "Fora da amostra, uma vez", "", VERDE),
        Painel("pv_dia", 136, 584, 1100, 472, "03", "DIA A DIA", "Alertas e acertos no teste",
               "O teste foi feito uma vez: não segue período, tipo de dia nem frequência · segue o filtro de linha", VERDE),
        Painel("pv_linhas", 1252, 584, 636, 472, "04", "LINHAS", "Onde o modelo mais avisou",
               "Alertas no teste e quantos chegaram colados", VERDE),
    ]),
    Pag("qualidade", "Confiança", "Dá para", "confiar?", "QUALIDADE DO DADO", "qualidade", [
        Painel("q_cards", 136, 148, 1752, 330, cor=AZUL),
        Painel("q_dia", 136, 494, 1752, 562, "02", "DIA A DIA", "Cobertura e quedas do feed",
               "Em cada dia do recorte: quanto do dado virou intervalo e quanto foi descartado com o feed parado", AZUL),
    ]),
    Pag("simulador", "Simulador", "Simulador", "", "E SE O CONTROLE AGISSE", "simulador", [
        Painel("controle", 136, 148, 560, 908, "01", "E SE", "Espaçar os ônibus colados",
               "Quantos pares colados o controle consegue espaçar", VERDE, html_topo=76),
        Painel("sfaixa", 712, 148, 1176, 440, "02", "POR FAIXA", "Espera extra hoje e simulada", "", VERDE),
        Painel("ganho", 712, 604, 1176, 452, "03", "ONDE MAIS GANHA", "Linhas com maior ganho",
               "Ordem pela parte do ganho da rede · é o tamanho do problema, não ganho garantido", VERDE),
    ]),
    Pag("ficha", "Ficha da linha", "Ficha da", "linha", "UMA LINHA POR VEZ", "ficha", [
        # o carrossel (visual proprio) cobre o painel inteiro; a arte so desenha numero, olho e titulo
        Painel("carrossel", 136, 148, 1752, 484, "01", "LINHAS", "Gire e escolha a linha", cor=AMBAR),
        Painel("ffaixa", 136, 648, 860, 408, "02", "HORA DO DIA", "Espera por faixa horária",
               "Azul: com intervalos iguais · âmbar: a espera extra", AZUL),
        Painel("fdia", 1012, 648, 876, 408, "03", "DIA A DIA", "Espera extra por dia",
               "Barra clara: dia com evento na cidade · tracejado azul: média do período", AMBAR),
    ]),
    Pag("porque", "O que pesa", "O que", "pesa", "O QUE EXPLICA A ESPERA EXTRA", "porque", [
        Painel("plinhas", 136, 148, 1100, 560, "01", "INTERVALO OU COLADOS", "A espera extra segue os colados",
               "Só alta frequência · cada bolha é uma linha com 0,1% ou mais das horas · r: correlação entre as linhas", VERMELHO),
        Painel("ppontos", 1252, 148, 636, 560, "02", "PONTOS", "Ponto cheio não espera mais",
               "Últimos 28 dias, pontos pelo número de linhas · não segue período nem linha", AMBAR),
        Painel("pdias", 136, 724, 1100, 332, "03", "TIPO DE DIA", "Dia útil, sábado e domingo",
               "Ignora o filtro de tipo de dia · tracejado: todos os dias", AZUL),
        Painel("pleitura", 1252, 724, 636, 332, "04", "LEITURA", "O que muda na prática", "", VERDE),
    ]),
    Pag("acoes", "Onde agir", "Onde", "agir", "O QUE OS NÚMEROS SUGEREM", "acoes", [
        Painel("rotas", 136, 148, 860, 908, "01", "ROTAS", "Linhas que vão ao centro esperam mais",
               "Linhas agrupadas pelo trajeto que o nome diz · rede inteira: não segue o filtro de linha", AMBAR),
        Painel("operacao", 1012, 148, 876, 560, "02", "OPERAÇÃO", "Cinco ajustes na circulação",
               "Cada número segue o recorte dos filtros · a previsão vem do teste da fase 5", VERDE),
        Painel("corredores", 1012, 724, 876, 332, "03", "CORREDORES", "Onde a via pesa",
               "Últimos 28 dias, média dos pontos da avenida · tracejado: a rede · prioridade começa pela 1ª", AZUL),
    ]),
]
VISIVEIS = PAGINAS
POR_CHAVE = {p.chave: p for p in PAGINAS}


def area_html(p: Painel) -> tuple[int, int, int, int]:
    """Onde fica o visual HTML do painel: o painel inteiro se nao tem titulo, senao o miolo."""
    if not p.titulo:
        return p.x, p.y, p.w, p.h
    x, y, w, h = p.miolo()
    return x, y + p.html_topo, w, h - p.html_topo


# ---------------------------------------------------------------------------
# Auxiliares de PBIR
# ---------------------------------------------------------------------------
def L(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def txt(s: str) -> dict:
    return L("'" + s.replace("'", "''") + "'")


def num(x: float) -> dict:
    return L(f"{x}D")


def inteiro(x: int) -> dict:
    return L(f"{x}L")


def cor(hexa: str) -> dict:
    return {"solid": {"color": txt(hexa)}}


def medida_ref(nome: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Medidas"}}, "Property": nome}}


def coluna_ref(tabela: str, col: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": tabela}}, "Property": col}}


def proj_medida(nome: str, rotulo: str | None = None) -> dict:
    p = {"field": medida_ref(nome), "queryRef": f"_Medidas.{nome}", "nativeQueryRef": nome}
    if rotulo:
        p["displayName"] = rotulo
    return p


def proj_coluna(tabela: str, col: str, rotulo: str | None = None) -> dict:
    p = {"field": coluna_ref(tabela, col), "queryRef": f"{tabela}.{col}", "nativeQueryRef": col}
    if rotulo:
        p["displayName"] = rotulo
    return p


def props(**kw) -> list:
    return [{"properties": kw}]


def sem_moldura() -> dict:
    """Conteiner transparente: a moldura esta na arte."""
    return {
        "background": props(show=L("false")),
        "border": props(show=L("false")),
        "dropShadow": props(show=L("false")),
        "title": props(show=L("false")),
        "visualHeader": props(show=L("false")),
        "padding": props(left=num(0), top=num(0), right=num(0), bottom=num(0)),
    }


# ---------------------------------------------------------------------------
# Pagina e visuais
# ---------------------------------------------------------------------------
class Pagina:
    def __init__(self, pag: Pag):
        self.pag = pag
        self.nome = nome_pagina(pag.chave)
        self.visuais: list[dict] = []
        self.z = 1000

    def add(self, chave: str, x, y, w, h, visual: dict) -> str:
        self.z += 100
        nome = nome_visual(f"{self.pag.chave}/{chave}")
        self.visuais.append({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.13.0/schema.json",
            "name": nome,
            "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
            "visual": {**visual, "visualContainerObjects": sem_moldura(), "drillFilterOtherVisuals": True},
        })
        return nome

    # --- cartao com texto (cardVisual): so o selo da carga ---------------------------------
    def valor(self, chave: str, medida: str, x, y, w, h, tamanho: int, cor_txt: str) -> str:
        padrao = {"selector": {"id": "default"}}
        objetos = {
            "outline": [{"properties": {"show": L("false")}, **padrao}],
            "border": [{"properties": {"show": L("false")}, **padrao}],
            "divider": [{"properties": {"show": L("false")}, **padrao}],
            "accentBar": [{"properties": {"show": L("false")}, **padrao}],
            "cardImage": [{"properties": {"show": L("false"), "addBackground": L("false")}, **padrao}],
            "padding": [{"properties": {"paddingIndividual": L("false")}, **padrao}],
            "value": [{"properties": {"fontFamily": txt(FONTE_FORTE), "bold": L("false"), "fontColor": cor(cor_txt),
                                      "horizontalAlignment": txt("left"), "showBlankAs": txt("–"),
                                      "fontSize": num(tamanho)}, **padrao}],
            "label": [{"properties": {"show": L("false")}, **padrao}],
            "layout": [{"properties": {"backgroundShow": L("false"), "paddingUniform": inteiro(0),
                                       "paddingIndividual": L("false"), "topOuterMargin": inteiro(0)}, **padrao},
                       {"properties": {"cellPadding": inteiro(0)}}],
            "fillCustom": props(show=L("false")),
            "cardCalloutArea": [{"properties": {"show": L("false")}, **padrao}],
            "smallMultiplesCellBackGround": [{"properties": {"backgroundShow": L("false")}, **padrao}],
        }
        return self.add(chave, x, y, w, h, {
            "visualType": "cardVisual",
            "query": {"queryState": {"Data": {"projections": [proj_medida(medida)]}}},
            "objects": objetos,
        })

    # --- painel HTML (visual HTML Content, medida de paineis.py) -------------------------------
    def html(self, chave: str, medida: str, x, y, w, h) -> str:
        return self.add(chave, x, y, w, h, {
            "visualType": HTML_VISUAL,
            "query": {"queryState": {"content": {"projections": [proj_medida(medida)]}}},
            "objects": {"compatibility": props(legacyRendering=L("true"))},
        })

    # --- carrossel de linhas (visual proprio): o cartao do centro filtra a pagina ---------------
    def carrossel(self, p: Painel) -> str:
        estado = {"linha": {"projections": [proj_coluna("dim_linha", "route_id")]}}
        for papel, medida in CARROSSEL_PAPEIS:
            estado[papel] = {"projections": [proj_medida(medida)]}
        return self.add(p.chave, p.x, p.y, p.w, p.h, {"visualType": CARROSSEL, "query": {"queryState": estado}})

    def paineis_html(self) -> None:
        from paineis import PAINEIS
        for (pag, painel), (medida, _, _) in PAINEIS.items():
            if pag == self.pag.chave:
                self.html(painel, medida, *area_html(self.pag.p(painel)))

    # --- filtros --------------------------------------------------------------------------
    def segmentacao(self, chave: str, tabela: str, col: str, x, y, w, h, modo: str = "Dropdown", unico: bool = False,
                    padrao=None, grupo: str | None = None, busca: bool = False, horizontal: bool = False,
                    texto: int = 14) -> str:
        objs = {
            "data": props(mode=txt(modo)),
            "header": props(show=L("false")),
            "items": props(fontColor=cor(TEXTO), background=cor(PAINEL2), textSize=num(texto),
                           fontFamily=txt(FONTE_FORTE), outlineColor=cor(BORDA)),
            "selection": props(singleSelect=L("true" if unico else "false"),
                               selectAllCheckboxEnabled=L("false" if unico else "true")),
        }
        geral = {}
        if busca:
            geral["selfFilterEnabled"] = L("true")
        if horizontal:
            geral["orientation"] = L("1D")
        if padrao is not None:
            valor = f"{padrao}D" if isinstance(padrao, float) else "'" + padrao.replace("'", "''") + "'"
            geral["filter"] = {"filter": {
                "Version": 2, "From": [{"Name": "s", "Entity": tabela, "Type": 0}],
                "Where": [{"Condition": {"In": {
                    "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": col}}],
                    "Values": [[{"Literal": {"Value": valor}}]]}}}]}}
        if geral:
            objs["general"] = [{"properties": geral}]
        visual = {"visualType": "slicer",
                  "query": {"queryState": {"Values": {"projections": [dict(proj_coluna(tabela, col), active=True)]}}},
                  "objects": objs}
        if grupo:
            visual["syncGroup"] = {"groupName": grupo, "fieldChanges": True, "filterChanges": True}
        return self.add(chave, x, y, w, h, visual)

    def filtros(self) -> None:
        for chave, tabela, col, _, x, w, padrao, unico, busca in FILTROS:
            self.segmentacao(f"filtro_{chave}", tabela, col, x, FILTRO_Y, w, FILTRO_H, unico=unico, padrao=padrao,
                             grupo=f"filtro_{chave}", busca=busca)
        self.valor("selo", "Dados até", 592, 100, 460, 22, tamanho=11, cor_txt=VERDE)

    def navegador(self) -> None:
        """Menu lateral: navegador nativo invisivel sobre os itens desenhados na arte."""
        estados = ["default", "hover", "press", "selected", "disabled"]

        def desliga():
            return [{"properties": {"show": L("false")}, "selector": {"id": e}} for e in estados] + props(show=L("false"))

        self.add("navegador", 0, NAV_TOPO, TRILHO, NAV_ITEM * len(VISIVEIS), {
            "visualType": "pageNavigator",
            "objects": {"layout": props(orientation=L("1D")), "fill": desliga(), "text": desliga(),
                        "outline": desliga()}})

    def json_pagina(self) -> dict:
        p = self.pag
        return {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
            "name": self.nome, "displayName": p.nome, "displayOption": "FitToPage",
            "height": p.altura, "width": p.largura,
            "objects": {
                "background": props(
                    image={"image": {
                        "name": txt(f"fundo_{p.chave}.png"),
                        "url": {"expr": {"ResourcePackageItem": {
                            "PackageName": "RegisteredResources", "PackageType": 1,
                            "ItemName": f"fundo_{p.chave}.png"}}},
                        "scaling": txt("Fill")}},
                    color=cor(FUNDO), transparency=num(0)),
                "outspace": props(color=cor(FUNDO)),
            },
        }


# ---------------------------------------------------------------------------
# Paginas
# ---------------------------------------------------------------------------
def construir() -> list[Pagina]:
    paginas = []
    for pag in PAGINAS:
        pg = Pagina(pag)
        pg.navegador()
        pg.filtros()
        if pag.chave == "simulador":
            x, y, w, _ = pag.p("controle").miolo()
            pg.segmentacao("espacamento", "sel_espacamento", "espacamento", x, y, w, 56, modo="Basic", unico=True,
                           padrao=0.5, horizontal=True, texto=16)
        if pag.chave == "ficha":
            pg.carrossel(pag.p("carrossel"))
        pg.paineis_html()
        paginas.append(pg)
    return paginas


# ---------------------------------------------------------------------------
# Tema
# ---------------------------------------------------------------------------
def tema() -> dict:
    return {
        "name": "Radar",
        "dataColors": [AZUL, AMBAR, VERMELHO, VERDE, SUAVE, APAGADO, "#5B6BA8", "#C98BB0"],
        "foreground": TEXTO, "foregroundNeutralSecondary": SUAVE, "foregroundNeutralTertiary": APAGADO,
        "background": FUNDO, "backgroundLight": PAINEL, "backgroundNeutral": PAINEL2,
        "tableAccent": AMBAR, "good": VERDE, "bad": VERMELHO, "neutral": AMBAR,
        "maximum": AMBAR, "center": AZUL, "minimum": PAINEL2,
        "textClasses": {
            "callout": {"fontSize": 40, "fontFace": FONTE_FORTE, "color": TEXTO},
            "title": {"fontSize": 16, "fontFace": FONTE_FORTE, "color": TEXTO},
            "header": {"fontSize": 13, "fontFace": FONTE_FORTE, "color": SUAVE},
            "label": {"fontSize": 12, "fontFace": FONTE, "color": SUAVE},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": False}],
                "border": [{"show": False}],
                "dropShadow": [{"show": False}],
                "visualHeader": [{"show": False}],
                "visualTooltip": [{"background": {"solid": {"color": PAINEL2}},
                                   "titleFontColor": {"solid": {"color": SUAVE}},
                                   "valueFontColor": {"solid": {"color": TEXTO}},
                                   "fontSize": 12}],
            }},
            "page": {"*": {"background": [{"color": {"solid": {"color": FUNDO}}, "transparency": 0}],
                           "outspace": [{"color": {"solid": {"color": FUNDO}}}]}},
            "slicer": {"*": {
                "items": [{"fontColor": {"solid": {"color": TEXTO}}, "background": {"solid": {"color": PAINEL2}}}],
                "dropdown": [{"background": {"solid": {"color": PAINEL2}}}],
            }},
        },
    }
