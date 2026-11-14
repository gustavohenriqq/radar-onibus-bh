"""Modelo semantico do Power BI (TMDL): tabelas, relacoes e medidas.

As medidas repetem as formulas de painel/consultas.py (METRICAS), que repetem
servico/metricas.py: toda metrica e razao de somas, entao qualquer filtro do
relatorio da o mesmo numero do SQL. A conferencia (powerbi/conferencia/)
compara as duas contas.

Nenhum numero do relatorio e digitado: tudo sai de medida.
"""
from __future__ import annotations

import ast
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NS = uuid.UUID("3f6c2a1e-8b4d-4c7a-9e21-5a0b7c1d2e01")

# Paleta de sinalizacao: fundo tinta, letreiro ambar. Cada cor tem um papel so.
FUNDO, PAINEL, PAINEL2, BORDA = "#0A0E1C", "#111729", "#182038", "#2A3456"
TEXTO, SUAVE, APAGADO = "#F4F6FB", "#C9D0E4", "#9AA3C2"
AMBAR = "#FFB347"     # espera extra (o problema) e a marca
AZUL = "#6AA8FF"      # espera regular, a base
VERDE = "#42D392"     # ganho, melhora, acerto
VERMELHO = "#FF6B6B"  # piora, colados, o pior

# Escala da espera extra (min): da tinta ao ambar claro (mais quente, mais espera).
ESCALA = [(0.5, "#18203A"), (1.0, "#1F2B47"), (1.5, "#2E3550"), (2.0, "#4A3F4F"), (2.5, "#6E4A45"),
          (3.0, "#94563A"), (3.5, "#B9652F"), (4.5, "#DE7A2C"), (6.0, "#F59A33"), (None, "#FFC15A")]

HORAS_MIN_PARADA = 25  # o mesmo corte do painel (painel/app.py)
TOP_CALOR = 30  # linhas no mapa de calor linha x faixa
# Faixas horarias da Gold (gold/seeds/faixa_horaria.csv): codigo, nome e horas, na ordem do dia
FAIXAS = [("madrugada", "Madrugada", "0h às 5h"), ("inicio_manha", "Início da manhã", "5h às 6h"),
          ("pico_manha", "Pico da manhã", "6h às 9h"), ("entre_picos", "Entre picos", "9h às 16h"),
          ("pico_tarde", "Pico da tarde", "16h às 20h"), ("noite", "Noite", "20h às 24h")]


def tag(*partes: str) -> str:
    return str(uuid.uuid5(NS, "/".join(partes)))


def nome_tmdl(nome: str) -> str:
    return nome if nome.isidentifier() and nome.isascii() else "'" + nome.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Tabelas do banco (Import do Neon, esquema radar)
# ---------------------------------------------------------------------------
SOMAS = [("grupos", "int64"), ("n", "int64"), ("soma", "double"), ("soma2_n", "double"), ("dev2", "double"),
         ("colados", "int64"), ("abaixo_60s", "int64"), ("reducao", "double"), ("pares", "int64"),
         ("pulo_primeiro", "int64"), ("pulo_colado", "int64"), ("var_n", "double")]

# tabela no modelo: (tabela no banco, colunas (nome, tipo), documentacao, passos M extras)
FREQ_M = ('    Freq = Table.AddColumn(Colunas, "frequencia", each if [alta_frequencia] then "alta" else "baixa", '
          'type text)')
TABELAS_BANCO = {
    "fato_linha": ("linha_dia_faixa", [
        ("route_id", "string"), ("direction_id", "int64"), ("data_bh", "dateTime"), ("faixa_horaria", "string"),
        ("ordem_faixa", "int64"), ("tipo_dia", "string"), ("alta_frequencia", "boolean"), *SOMAS],
        "Somas reagregaveis por linha, sentido, dia e faixa horaria (servico/exportar.py).", FREQ_M),
    "fato_hist": ("hist_dia", [
        ("data_bh", "dateTime"), ("tipo_dia", "string"), ("alta_frequencia", "boolean"), ("classe", "int64"),
        ("headways", "int64")],
        "Histograma do intervalo dividido pelo intervalo medio, por dia (classes de 0,05; a 80 junta 4 ou mais).",
        FREQ_M),
    "fato_paradas": ("paradas_28d", [
        ("stop_id", "string"), ("tipo_dia", "string"), ("alta_frequencia", "boolean"), *SOMAS,
        ("linhas", "int64"), ("stop_name", "string"), ("stop_lat", "double"), ("stop_lon", "double"),
        ("janela_ini", "dateTime"), ("janela_fim", "dateTime")],
        "Somas por ponto nos ultimos 28 dias. Sem linha: nao segue o filtro de linha nem o de periodo.", FREQ_M),
    "fato_qualidade": ("qualidade_diaria", [
        ("data_bh", "dateTime"), ("passagens", "int64"), ("passagens_validas", "int64"),
        ("headways", "int64"), ("headways_validos", "int64"), ("headways_feed_parado", "int64"),
        ("linhas", "int64"), ("cobertura_passagens", "double")],
        "Qualidade do dado por dia (marts/fct_qualidade_diaria).", None),
    "fato_previsao": ("ml_resumo", [
        ("data_bh", "dateTime"), ("conjunto", "string"), ("route_id", "string"), ("versao_modelo", "string"),
        ("limiar", "double"), ("exemplos", "int64"), ("positivos", "int64"), ("alertas", "int64"),
        ("acertos", "int64")],
        "Alertas e acertos do modelo de onibus colados (fase 5), por dia e linha.", None),
    "dim_linha": ("linhas", [("route_id", "string"), ("route_long_name", "string")],
                  "Nome de cada linha (routes.txt do GTFS).", None),
}

TIPO_M = {"string": "type text", "int64": "Int64.Type", "double": "type number", "dateTime": "type date",
          "boolean": "type logical"}
FORMATO_COLUNA = {"int64": "0", "double": "0.00", "dateTime": "dd/mm/yyyy"}

# Colunas com rotulo e ordem (rotulo -> coluna de ordem)
ORDENAR = {("dim_faixa", "faixa"): "ordem", ("dim_tipo_dia", "tipo"): "ordem",
           ("dim_frequencia", "frequencia_rotulo"): "ordem", ("dim_data", "dia_semana"): "dia_semana_ordem",
           ("dim_data", "semana_rotulo"): "semana", ("sel_periodo", "periodo"): "ordem",
           ("dim_linha", "trajeto"): "trajeto_ordem",
           ("dim_classe", "rotulo"): "classe"}
OCULTAS = {("fato_linha", c) for c, _ in SOMAS} | {("fato_paradas", c) for c, _ in SOMAS} | {
    ("fato_linha", "alta_frequencia"), ("fato_hist", "alta_frequencia"), ("fato_paradas", "alta_frequencia"),
    ("dim_faixa", "ordem"), ("dim_tipo_dia", "ordem"), ("dim_frequencia", "ordem"), ("sel_periodo", "ordem"),
    ("dim_data", "dia_semana_ordem"), ("dim_linha", "trajeto_ordem")}


def tmdl_coluna(tabela: str, nome: str, tipo: str, fonte: str | None = None, expressao: str | None = None,
                formato: str | None = None, so_data: bool = True) -> str:
    cab = f"\tcolumn {nome_tmdl(nome)}" + (f" = {expressao}" if expressao else "")
    linhas = [cab, f"\t\tdataType: {tipo}"]
    fmt = formato or FORMATO_COLUNA.get(tipo)
    if fmt:
        linhas.append(f"\t\tformatString: {fmt}")
    if (tabela, nome) in OCULTAS:
        linhas.append("\t\tisHidden")
    linhas += [f"\t\tlineageTag: {tag('coluna', tabela, nome)}", "\t\tsummarizeBy: none"]
    if not expressao:
        linhas.append(f"\t\tsourceColumn: {fonte or nome}")
    if (tabela, nome) in ORDENAR:
        linhas.append(f"\t\tsortByColumn: {ORDENAR[(tabela, nome)]}")
    if tipo == "dateTime" and so_data:
        linhas += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    linhas += ["", "\t\tannotation SummarizationSetBy = User", ""]
    return "\n".join(linhas)


def bloco(texto: str, tabs: int) -> str:
    """Expressao de varias linhas, recuada para dentro do objeto TMDL."""
    return "\n".join("\t" * tabs + l if l.strip() else "" for l in texto.strip("\n").splitlines())


def tmdl_tabela_banco(tabela: str) -> str:
    origem, colunas, doc, passo = TABELAS_BANCO[tabela]
    nomes = ", ".join(f'"{c}"' for c, _ in colunas)
    tipos = ", ".join(f'{{"{c}", {TIPO_M[t]}}}' for c, t in colunas)
    final = "Colunas"
    extra = ""
    cols = list(colunas)
    if passo:
        extra = passo + ",\n"
        final = "Freq"
        cols.append(("frequencia", "string"))
    m = f"""let
    Fonte = PostgreSQL.Database(ServidorPostgres, BancoPostgres),
    Tabela = Fonte{{[Schema = "radar", Item = "{origem}"]}}[Data],
    Selecao = Table.SelectColumns(Tabela, {{{nomes}}}),
    Colunas = Table.TransformColumnTypes(Selecao, {{{tipos}}}),
{extra}    Pronto = {final}
in
    Pronto"""
    corpo = "\n".join(tmdl_coluna(tabela, c, t) for c, t in cols)
    return (f"/// {doc}\ntable {tabela}\n\tlineageTag: {tag('tabela', tabela)}\n\n{corpo}\n"
            f"\tpartition {tabela} = m\n\t\tmode: import\n\t\tsource =\n{bloco(m, 4)}\n\n"
            "\tannotation PBI_ResultType = Table\n")


def tmdl_cargas() -> str:
    m = """let
    Fonte = PostgreSQL.Database(ServidorPostgres, BancoPostgres),
    Tabela = Fonte{[Schema = "radar", Item = "cargas"]}[Data],
    Selecao = Table.SelectColumns(Tabela, {"carregado_em", "de", "ate"}),
    // timestamptz chega como datetime na hora local da maquina (BRT no Desktop, UTC no servico): volta a UTC e passa a BH (-3, sem horario de verao)
    Fuso = DateTimeZone.ZoneHours(DateTimeZone.LocalNow()),
    Local = Table.TransformColumns(Selecao, {{"carregado_em", each if _ = null then null
        else if Value.Is(_, type datetimezone) then DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(_, -3))
        else DateTime.From(_) - #duration(0, Fuso + 3, 0, 0), type datetime}}),
    Colunas = Table.TransformColumnTypes(Local, {{"de", type date}, {"ate", type date}})
in
    Colunas"""
    corpo = "\n".join([tmdl_coluna("cargas", "carregado_em", "dateTime", formato="dd/mm/yyyy hh:nn", so_data=False),
                       tmdl_coluna("cargas", "de", "dateTime"), tmdl_coluna("cargas", "ate", "dateTime")])
    return (f"/// Uma linha por exportacao para o Neon (horario de BH). Diz ate que dia vao os dados.\n"
            f"table cargas\n\tlineageTag: {tag('tabela', 'cargas')}\n\n{corpo}\n"
            f"\tpartition cargas = m\n\t\tmode: import\n\t\tsource =\n{bloco(m, 4)}\n\n"
            "\tannotation PBI_ResultType = Table\n")


# ---------------------------------------------------------------------------
# Tabelas calculadas (dimensoes e seletores)
# ---------------------------------------------------------------------------
def eventos_do_painel() -> tuple[dict, dict]:
    """EVENTOS e FALHA_S de painel/app.py, lidos sem importar o Streamlit."""
    arvore = ast.parse((RAIZ / "painel" / "app.py").read_text(encoding="utf-8"))
    achados = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            nome = no.targets[0].id
            if nome == "EVENTOS":
                achados[nome] = ast.literal_eval(no.value)
            elif nome == "FALHA_S":  # dict comprehension: valor fixo para cada data da tupla
                gen = no.value.generators[0]
                datas = ast.literal_eval(gen.iter)
                achados[nome] = {d: ast.literal_eval(no.value.value) for d in datas}
    return achados["EVENTOS"], achados["FALHA_S"]


def dax_texto(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


LARGURA_EVENTO = 40  # caracteres por linha na lista de eventos (SVG nao quebra texto sozinho)


def quebrar(texto: str, largura: int = LARGURA_EVENTO, linhas: int = 2) -> list[str]:
    """Quebra o texto em ate `linhas` linhas; corta com reticencias o que sobrar."""
    saida, atual = [], ""
    palavras = texto.split()
    for i, p in enumerate(palavras):
        if len(atual) + len(p) + (1 if atual else 0) <= largura:
            atual = f"{atual} {p}" if atual else p
            continue
        saida.append(atual)
        atual = p
        if len(saida) == linhas:
            break
    else:
        if atual:
            saida.append(atual)
        return saida + [""] * (linhas - len(saida))
    ultima = saida[-1]
    while len(ultima) + 1 > largura:
        ultima = ultima.rsplit(" ", 1)[0]
    saida[-1] = ultima.rstrip(",;:") + "…"
    return saida


def calc_eventos() -> str:
    eventos, falhas = eventos_do_painel()
    datas = sorted(set(eventos) | set(falhas))
    linhas = []
    for d in datas:
        e = eventos.get(d, "")
        l1, l2, l3 = quebrar(e, linhas=3)
        n = sum(1 for x in (l1, l2, l3) if x)
        # DATATABLE so aceita constantes: data como texto ISO, nao DATE ( ... )
        linhas.append(f"{{ \"{d}\", {dax_texto(e)}, {dax_texto(l1)}, {dax_texto(l2)}, {dax_texto(l3)}, {n}, "
                      f"{'TRUE' if d in falhas else 'FALSE'} }}")
    return ('DATATABLE (\n    "data", DATETIME, "evento", STRING, "evento_l1", STRING, "evento_l2", STRING, '
            '"evento_l3", STRING, "evento_n", INTEGER, "falha_gps_s", BOOLEAN,\n    {\n        '
            + ",\n        ".join(linhas) + "\n    }\n)")


CALCULADAS = {
    "dim_data": (
        "Calendario dos dias com dado, com dia da semana, semana e eventos do painel web.",
        """
VAR d = CALENDAR ( MIN ( fato_linha[data_bh] ), MAX ( fato_linha[data_bh] ) )
RETURN
    ADDCOLUMNS (
        SELECTCOLUMNS ( d, "data", [Date] ),
        "rotulo", FORMAT ( [data], "dd/mm" ),
        "dia_semana", SWITCH ( WEEKDAY ( [data], 2 ), 1, "Seg", 2, "Ter", 3, "Qua", 4, "Qui", 5, "Sex", 6, "Sáb", "Dom" ),
        "dia_semana_ordem", WEEKDAY ( [data], 2 ),
        "semana", [data] - WEEKDAY ( [data], 2 ) + 1,
        "semana_rotulo", "Semana de " & FORMAT ( [data] - WEEKDAY ( [data], 2 ) + 1, "dd/mm" ),
        "evento", LOOKUPVALUE ( eventos[evento], eventos[data], [data] ),
        "falha_gps_s", LOOKUPVALUE ( eventos[falha_gps_s], eventos[data], [data] )
    )""",
        [("data", "dateTime", "dd/mm/yyyy"), ("rotulo", "string", None), ("dia_semana", "string", None),
         ("dia_semana_ordem", "int64", "0"), ("semana", "dateTime", "dd/mm/yyyy"), ("semana_rotulo", "string", None),
         ("evento", "string", None), ("falha_gps_s", "boolean", None)]),
    "eventos": ("Eventos na cidade e dias com falha de GPS nas linhas suplementares (copiados de painel/app.py).",
                None, [("data", "dateTime", "dd/mm/yyyy"), ("evento", "string", None), ("evento_l1", "string", None),
                       ("evento_l2", "string", None), ("evento_l3", "string", None), ("evento_n", "int64", "0"),
                       ("falha_gps_s", "boolean", None)]),
    "dim_faixa": (
        "Faixas horarias da Gold (gold/seeds/faixa_horaria.csv), com nome e horas.",
        '\nDATATABLE (\n    "faixa_horaria", STRING, "faixa", STRING, "horas", STRING, "ordem", INTEGER,\n    {\n'
        + ",\n".join(f'        {{ "{c}", "{n}", "{h}", {i} }}' for i, (c, n, h) in enumerate(FAIXAS, 1))
        + "\n    }\n)",
        [("faixa_horaria", "string", None), ("faixa", "string", None), ("horas", "string", None),
         ("ordem", "int64", "0")]),
    "dim_tipo_dia": (
        "Tipo de dia: util, sabado, domingo e feriado.",
        """
DATATABLE (
    "tipo_dia", STRING, "tipo", STRING, "ordem", INTEGER,
    { { "dia_util", "Dia útil", 1 }, { "sabado", "Sábado", 2 }, { "domingo_feriado", "Domingo e feriado", 3 } }
)""",
        [("tipo_dia", "string", None), ("tipo", "string", None), ("ordem", "int64", "0")]),
    "dim_frequencia": (
        "Alta frequencia: intervalo medio de ate 15 min na linha, sentido, dia e faixa.",
        """
DATATABLE (
    "frequencia", STRING, "frequencia_rotulo", STRING, "ordem", INTEGER,
    { { "alta", "Alta (até 15 min)", 1 }, { "baixa", "Baixa", 2 } }
)""",
        [("frequencia", "string", None), ("frequencia_rotulo", "string", None), ("ordem", "int64", "0")]),
    "dim_classe": (
        "Classes do histograma: intervalo dividido pelo intervalo medio, de 0,05 em 0,05.",
        """
SELECTCOLUMNS (
    GENERATESERIES ( 0, 80, 1 ),
    "classe", [Value],
    "inicio", [Value] * 0.05,
    "rotulo", IF ( [Value] >= 80, "4+", FORMAT ( [Value] * 0.05, "0.00" ) )
)""",
        [("classe", "int64", "0"), ("inicio", "double", "0.00"), ("rotulo", "string", None)]),
    "sel_periodo": (
        "Seletor de periodo: cada dia aparece em todas as janelas que o contem. Filtra dim_data nos dois sentidos.",
        """
VAR ultimo = MAX ( fato_linha[data_bh] )
VAR dias = CALENDAR ( MIN ( fato_linha[data_bh] ), ultimo )
RETURN
    UNION (
        SELECTCOLUMNS ( dias, "periodo", "Tudo desde 15/09", "ordem", 1, "data", [Date] ),
        SELECTCOLUMNS ( FILTER ( dias, [Date] > ultimo - 28 ), "periodo", "Últimos 28 dias", "ordem", 2, "data", [Date] ),
        SELECTCOLUMNS ( FILTER ( dias, [Date] > ultimo - 7 ), "periodo", "Últimos 7 dias", "ordem", 3, "data", [Date] )
    )""",
        [("periodo", "string", None), ("ordem", "int64", "0"), ("data", "dateTime", "dd/mm/yyyy")]),
    "sel_espacamento": (
        "Parametro do simulador: parte dos pares colados que seria espacada.",
        """
SELECTCOLUMNS ( GENERATESERIES ( 0, 1, 0.25 ), "espacamento", [Value] )""",
        [("espacamento", "double", "0%")]),
}


def tmdl_calculada(tabela: str) -> str:
    doc, dax, colunas = CALCULADAS[tabela]
    if dax is None:
        dax = calc_eventos()
    corpo = "\n".join(tmdl_coluna(tabela, c, t, fonte=f"[{c}]", formato=f) for c, t, f in colunas)
    return (f"/// {doc}\ntable {tabela}\n\tlineageTag: {tag('tabela', tabela)}\n\n{corpo}\n"
            f"\tpartition {tabela} = calculated\n\t\tmode: import\n\t\tsource =\n{bloco(dax, 4)}\n")


def tmdl_dim_linha() -> str:
    """dim_linha vem do banco e ganha o rotulo 'linha · nome' para o filtro."""
    t = tmdl_tabela_banco("dim_linha")
    rotulo = tmdl_coluna("dim_linha", "rotulo", "string",
                         expressao='dim_linha[route_id] & " · " & dim_linha[route_long_name]')
    novas = [rotulo] + [tmdl_coluna("dim_linha", nome, tipo, expressao=expr_trajeto(saida))
                        for nome, tipo, saida in (("trajeto", "string", "rotulo"), ("trajeto_ordem", "int64", "ordem"))]
    return t.replace("\tpartition dim_linha", "\n".join(novas) + "\n\tpartition dim_linha", 1)


# Trajeto pelo nome da linha (pagina Onde agir). Estacao: o nome cita uma estacao de integracao.
# Centro: cita Centro, Savassi ou Hospitais (a area central).
TRAJETOS = [("Da estação ao centro", "est && cen"), ("Do bairro ao centro", "cen"),
            ("Entre bairros", "NOT est"), ("Do bairro à estação", "TRUE ()")]


def expr_trajeto(saida: str) -> str:
    casos = ", ".join(f'{cond}, {f"{dax_texto(rot)}" if saida == "rotulo" else i}'
                      for i, (rot, cond) in enumerate(TRAJETOS, 1))
    return ('VAR n = dim_linha[route_long_name] VAR est = CONTAINSSTRING ( n, "Estaç" ) '
            'VAR cen = CONTAINSSTRING ( n, "Centro" ) || CONTAINSSTRING ( n, "Savassi" ) || '
            f'CONTAINSSTRING ( n, "Hospita" ) RETURN SWITCH ( TRUE (), {casos} )')


RELACOES = [
    # (de, para, ambos os sentidos)
    ("fato_linha.data_bh", "dim_data.data", False),
    ("fato_linha.route_id", "dim_linha.route_id", False),
    ("fato_linha.faixa_horaria", "dim_faixa.faixa_horaria", False),
    ("fato_linha.tipo_dia", "dim_tipo_dia.tipo_dia", False),
    ("fato_linha.frequencia", "dim_frequencia.frequencia", False),
    ("fato_hist.data_bh", "dim_data.data", False),
    ("fato_hist.tipo_dia", "dim_tipo_dia.tipo_dia", False),
    ("fato_hist.frequencia", "dim_frequencia.frequencia", False),
    ("fato_hist.classe", "dim_classe.classe", False),
    ("fato_paradas.tipo_dia", "dim_tipo_dia.tipo_dia", False),
    ("fato_paradas.frequencia", "dim_frequencia.frequencia", False),
    ("fato_qualidade.data_bh", "dim_data.data", False),
    ("fato_previsao.data_bh", "dim_data.data", False),
    ("fato_previsao.route_id", "dim_linha.route_id", False),
    ("sel_periodo.data", "dim_data.data", True),
]


def tmdl_relacoes() -> str:
    partes = []
    for de, para, ambos in RELACOES:
        p = [f"relationship {tag('relacao', de, para)}"]
        if ambos:
            p.append("\tcrossFilteringBehavior: bothDirections")
        p += [f"\tfromColumn: {de}", f"\ttoColumn: {para}", ""]
        partes.append("\n".join(p))
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# Medidas
# ---------------------------------------------------------------------------
L, P = "fato_linha", "fato_paradas"
SEM_PERIODO = "REMOVEFILTERS ( sel_periodo ), REMOVEFILTERS ( dim_data )"


def s(t: str, c: str) -> str:
    return f"SUM ( {t}[{c}] )"


def escala_cor(expr: str, letra: bool = False) -> str:
    """SWITCH em degraus da ESCALA: fundo da celula (ou cor da letra, clara no escuro e escura no claro)."""
    casos = []
    for i, (limite, hexa) in enumerate(ESCALA):
        valor = (TEXTO if i < 6 else FUNDO) if letra else hexa
        if limite is None:
            casos.append(f'"{valor}"')
        else:
            casos.append(f'v < {limite}, "{valor}"')
    return (f"VAR v = {expr}\nRETURN\n    IF ( ISBLANK ( v ), BLANK (),\n        SWITCH ( TRUE (),\n            "
            + ",\n            ".join(casos) + "\n        )\n    )")


def svg(corpo: str, w: int, h: int) -> str:
    """Prefixo e sufixo de um SVG em data URL (o # das cores vira %23)."""
    return (f"\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
            f"viewBox='0 0 {w} {h}'>\" & {corpo} & \"</svg>\"")


def hexa(c: str) -> str:
    return c.replace("#", "%23")


def medidas() -> list[tuple]:
    """(nome, DAX, formato, pasta, descricao, opcoes). opcoes: imagem, oculta."""
    m = []

    def add(nome, dax, fmt, pasta, doc, **op):
        m.append((nome, dax, fmt, pasta, doc, op))

    # --- Base: as 14 metricas do painel, sobre fato_linha ---------------------------------
    b = "Base"
    add("Grupos", s(L, "grupos"), "#,0", b, "Grupos linha x sentido x parada x dia x faixa com 3 ou mais intervalos.")
    add("Intervalos", s(L, "n"), "#,0", b, "Intervalos validos entre onibus da mesma linha (headways).")
    add("Horas de serviço", f"{s(L, 'soma')} / 3600", "#,0", b, "Tempo coberto pelos intervalos medidos, em horas.")
    add("Espera regular", f"DIVIDE ( {s(L, 'soma2_n')}, {s(L, 'soma')} ) / 2 / 60", "0.00", b,
        "Espera media com os mesmos onibus em intervalos iguais (min). sum(soma2_n) / 2 / sum(soma) / 60.")
    add("Espera extra", f"DIVIDE ( {s(L, 'dev2')}, {s(L, 'soma')} ) / 2 / 60", "0.00", b,
        "Espera a mais por passageiro, so pela irregularidade dos intervalos (min). sum(dev2) / 2 / sum(soma) / 60.")
    add("Volume", f"{s(L, 'dev2')} / 2 / 60 / 3600", "#,0", b,
        "Espera extra vezes horas de servico (min x h). Ordena linhas e pontos pelo peso na rede.")
    add("Colados", f"DIVIDE ( {s(L, 'colados')}, {s(L, 'n')} )", "0.0%", b,
        "Intervalos menores que 1/4 do intervalo medio do grupo.")
    add("Abaixo de 60 s", f"DIVIDE ( {s(L, 'abaixo_60s')}, {s(L, 'n')} )", "0.0%", b,
        "Intervalos menores que 60 segundos.")
    add("Corte sem colagem", f"DIVIDE ( {s(L, 'reducao')}, {s(L, 'dev2')} )", "0.0%", b,
        "Parte da espera extra que some se o onibus atrasado passasse no meio do caminho entre os dois.")
    add("Intervalos colados", s(L, "colados"), "#,0", b, "Quantidade de intervalos colados.")
    add("Pares colados", s(L, "pares"), "#,0", b, "Colados com o intervalo anterior nao colado.")
    add("Colado no início", s(L, "pulo_primeiro"), "#,0", b, "Colados no primeiro intervalo do grupo.")
    add("Colado atrás de colado", s(L, "pulo_colado"), "#,0", b, "Terceiro onibus em diante de um comboio.")
    add("Viés de interpolação", f"DIVIDE ( {s(L, 'var_n')}, {s(L, 'soma')} ) / 60", "0.000", b,
        "Quanto o erro de estimar a hora de passagem infla a espera extra (min).")
    add("Viés de interpolação %", f"DIVIDE ( {s(L, 'var_n')}, {s(L, 'dev2')} / 2 )", "0.0%", b,
        "Vies de interpolacao como parte da espera extra.")

    # --- Leitura: combinacoes das metricas ---------------------------------------------
    r = "Leitura"
    add("Espera média", "[Espera regular] + [Espera extra]", "0.00", r, "Espera media no ponto (min).")
    add("Custo da irregularidade", "DIVIDE ( [Espera extra], [Espera regular] )", "+0%;-0%;0%", r,
        "Espera extra sobre a espera regular.")
    add("Colados atrás de colado %",
        "DIVIDE ( [Colado atrás de colado], [Pares colados] + [Colado no início] + [Colado atrás de colado] )",
        "0.0%", r, "Dos colados, quantos sao o 3o onibus em diante (fora da conta do corte).")
    add("Linhas medidas", f"DISTINCTCOUNT ( {L}[route_id] )", "#,0", r, "Linhas com intervalo medido no recorte.")
    add("Dias medidos", f"DISTINCTCOUNT ( {L}[data_bh] )", "#,0", r, "Dias com intervalo medido no recorte.")
    add("Volume da rede", "CALCULATE ( [Volume], REMOVEFILTERS ( dim_linha ) )", "#,0", r,
        "Volume da rede inteira no recorte, sem o filtro de linha.")
    add("Parte da espera extra", "DIVIDE ( [Volume], [Volume da rede] )", "0.0%", r,
        "Parte da espera extra da rede que esta na linha (ou no recorte).")
    add("Posição",
        "VAR v = [Volume]\nRETURN\n    IF ( NOT ISBLANK ( v ) && HASONEVALUE ( dim_linha[route_id] ),\n"
        "        COUNTROWS ( FILTER ( ALL ( dim_linha ), [Volume] > v ) ) + 1 )",
        "0", r, "Posicao da linha pelo volume, entre todas as linhas da rede no recorte.")
    add("Linhas na rede", "COUNTROWS ( FILTER ( ALL ( dim_linha ), NOT ISBLANK ( [Volume] ) ) )", "0", r,
        "Linhas com espera medida no recorte, sem o filtro de linha.")
    add("Posição texto",
        'IF ( NOT ISBLANK ( [Posição] ), FORMAT ( [Posição], "0" ) & "ª de " & FORMAT ( [Linhas na rede], "0" ) )',
        None, r, "Posicao no ranking em texto: 12a de 311.")
    tabela_vol = ("VAR t = FILTER ( ADDCOLUMNS ( ALL ( dim_linha ), \"@v\", [Volume] ), "
                  "NOT ISBLANK ( [@v] ) )\nVAR tot = SUMX ( t, [@v] )")
    add("Linhas para 80%",
        tabela_vol + "\nVAR t2 = ADDCOLUMNS ( t, \"@antes\", VAR x = [@v] RETURN SUMX ( FILTER ( t, [@v] > x ), [@v] ) )"
        "\nRETURN\n    IF ( tot > 0, COUNTROWS ( FILTER ( t2, [@antes] < 0.8 * tot ) ) )",
        "0", r, "Menor numero de linhas que somam 80% da espera extra da rede (ordem pelo volume).")
    add("Linhas para 80% %", "DIVIDE ( [Linhas para 80%], [Linhas na rede] )", "0%", r,
        "Linhas para 80% sobre as linhas da rede.")
    add("Parte acumulada",
        "VAR v = [Volume]\n" + tabela_vol +
        "\nRETURN\n    IF ( NOT ISBLANK ( v ) && HASONEVALUE ( dim_linha[route_id] ),\n"
        "        DIVIDE ( SUMX ( FILTER ( t, [@v] >= v ), [@v] ), tot ) )",
        "0%", r, "Parte da espera extra somada desta linha para cima no ranking (curva de Pareto).")
    add("Pareto parte",
        f"IF ( [Posição] <= [Linhas para 80%] + 15, [Parte da espera extra] )", "0.0%", r,
        "Parte da espera extra so das linhas do grafico de concentracao (as do 80% e mais 15).", oculta=True)
    add("Pareto acumulada", f"IF ( [Posição] <= [Linhas para 80%] + 15, [Parte acumulada] )", "0%", r,
        "Parte acumulada so das linhas do grafico de concentracao.", oculta=True)
    add("Linha de 80%", "IF ( NOT ISBLANK ( [Pareto parte] ), 0.8 )", "0%", r,
        "Referencia de 80% no grafico de concentracao.", oculta=True)
    add("Calor top", f"IF ( [Posição] <= {TOP_CALOR}, [Espera extra] )", "0.0", r,
        f"Espera extra so nas {TOP_CALOR} linhas de maior volume (mapa de calor linha x faixa).")

    # --- Periodo anterior --------------------------------------------------------------
    pa = "Comparação"
    janela = ("VAR ini = MIN ( dim_data[data] )\nVAR fim = MAX ( dim_data[data] )\nVAR n = INT ( fim - ini ) + 1\n"
              f"VAR primeiro = CALCULATE ( MIN ( dim_data[data] ), {SEM_PERIODO} )")
    add("Dias no período", "VAR ini = MIN ( dim_data[data] )\nVAR fim = MAX ( dim_data[data] )\n"
        "RETURN IF ( NOT ISBLANK ( ini ), INT ( fim - ini ) + 1 )", "0", pa, "Dias de calendario no periodo.")
    add("Espera extra anterior",
        janela + f"\nRETURN\n    IF ( ini - n >= primeiro,\n        CALCULATE ( [Espera extra], {SEM_PERIODO},\n"
        "            dim_data[data] >= ini - n, dim_data[data] <= ini - 1 ) )",
        "0.00", pa, "Espera extra nos dias logo antes do periodo, com o mesmo numero de dias. Em branco se faltar dado.")
    add("Δ espera extra", "VAR a = [Espera extra anterior]\nRETURN IF ( NOT ISBLANK ( a ), [Espera extra] - a )",
        "+0.00;-0.00;0.00", pa, "Espera extra menos a do periodo anterior (min).")
    add("Texto da variação",
        "VAR d = [Δ espera extra]\nRETURN\n    IF ( ISBLANK ( d ), \"Sem período anterior completo para comparar\",\n"
        "        IF ( d > 0, \"▲ +\", \"▼ −\" ) & FORMAT ( ABS ( d ), \"0.00\" ) & \" min contra os \"\n"
        "            & [Dias no período] & \" dias anteriores\" )",
        None, pa, "Variacao da espera extra contra o periodo anterior, em texto.")
    add("Cor da variação", f'IF ( [Δ espera extra] > 0, "{VERMELHO}", IF ( [Δ espera extra] < 0, "{VERDE}", "{SUAVE}" ) )',
        None, "Cores", "Vermelho quando a espera extra subiu, verde quando caiu.", oculta=True)

    # --- Textos do relatorio --------------------------------------------------------------
    t = "Textos"
    add("Espera extra texto", 'IF ( NOT ISBLANK ( [Espera extra] ), "+" & FORMAT ( [Espera extra], "0.00" ) & " min" )',
        None, t, "A espera extra do recorte, para o numero grande da capa.")
    add("Recorte",
        'VAR ini = MIN ( dim_data[data] )\nVAR fim = MAX ( dim_data[data] )\n'
        'VAR tipo = IF ( HASONEVALUE ( dim_tipo_dia[tipo] ), LOWER ( VALUES ( dim_tipo_dia[tipo] ) ), "todos os dias" )\n'
        'VAR freq = IF ( HASONEVALUE ( dim_frequencia[frequencia] ),\n'
        '    IF ( VALUES ( dim_frequencia[frequencia] ) = "alta", "alta frequência", "baixa frequência" ), "todas as frequências" )\n'
        'VAR nl = COUNTROWS ( VALUES ( dim_linha[route_id] ) )\n'
        'VAR linhas = IF ( ISFILTERED ( dim_linha ), FORMAT ( nl, "0" ) & IF ( nl = 1, " linha escolhida", " linhas escolhidas" ), "rede inteira" )\n'
        'RETURN\n    UPPER ( FORMAT ( ini, "dd/mm" ) & " a " & FORMAT ( fim, "dd/mm" ) & "  ·  " & tipo & "  ·  " & freq & "  ·  " & linhas )',
        None, t, "Filtros em vigor, em uma linha.")
    add("Frase da espera",
        'IF ( NOT ISBLANK ( [Espera média] ),\n'
        '    "Quem chega ao ponto espera em média " & FORMAT ( [Espera média], "0.0" ) & " min pelo ônibus. "\n'
        '    & "Com os mesmos ônibus em intervalos iguais, seriam " & FORMAT ( [Espera regular], "0.0" ) & " min." )',
        None, t, "Frase da capa.")
    add("Dados até",
        'VAR ate = MAX ( cargas[ate] )\nVAR quando = MAX ( cargas[carregado_em] )\n'
        'RETURN "DADOS ATÉ " & FORMAT ( ate, "dd/mm/yyyy" ) & "  ·  CARGA " & FORMAT ( quando, "dd/mm hh:nn" )',
        None, t, "Selo do cabecalho: ultimo dia com dado e hora da ultima exportacao (horario de BH).")
    add("Nome da linha", 'IF ( HASONEVALUE ( dim_linha[route_id] ), VALUES ( dim_linha[route_long_name] ) )', None, t,
        "Nome da linha em foco (ficha e dica).")
    add("Linha em foco", 'IF ( HASONEVALUE ( dim_linha[route_id] ), "LINHA " & VALUES ( dim_linha[route_id] ) )', None, t,
        "Codigo da linha em foco.")
    add("Texto 80%",
        '"de " & FORMAT ( [Linhas na rede], "0" ) & " linhas somam 80% da espera extra da rede ("\n'
        '    & FORMAT ( [Linhas para 80% %], "0%" ) & " das linhas)"',
        None, t, "Legenda do numero da concentracao.")
    add("Evento do dia", 'IF ( HASONEVALUE ( dim_data[data] ),\n'
        '    VAR e = VALUES ( dim_data[evento] )\n    VAR f = VALUES ( dim_data[falha_gps_s] )\n'
        '    RETURN IF ( e <> "", e, IF ( f, "GPS das suplementares falhou em parte do dia" ) ) )',
        None, t, "Evento achado em noticias, ou falha de GPS das linhas S, no dia.")
    add("Marca de evento",
        'IF ( HASONEVALUE ( dim_data[data] ) && VALUES ( dim_data[evento] ) <> "", [Espera extra] )',
        "0.00", t, "Espera extra so nos dias com evento: vira coluna dourada no grafico dia a dia.")
    add("Calor texto",
        'VAR v = [Espera extra]\nVAR e = IF ( HASONEVALUE ( dim_data[data] ), VALUES ( dim_data[evento] ) )\n'
        'RETURN IF ( NOT ISBLANK ( v ), FORMAT ( v, "0.0" ) & IF ( e <> "", " ◆" ) )',
        None, t, "Espera extra em texto, com losango nos dias de evento (calendario).")
    add("Calor top texto", 'VAR v = [Calor top]\nRETURN IF ( NOT ISBLANK ( v ), FORMAT ( v, "0.0" ) )', None, t,
        "Texto do mapa de calor linha x faixa.")

    # --- Carrossel da Ficha (visual proprio, powerbi/carrossel) -------------------------------
    cr = "Carrossel"
    por_dia = ('CONCATENATEX ( VALUES ( dim_data[data] ),\n'
               '        VAR v = [Espera extra]\n        RETURN IF ( ISBLANK ( v ), "", FORMAT ( v, "0.000", "en-US" ) ),\n'
               '        ";", dim_data[data], ASC )')
    add("Carrossel tendência", f"IF ( NOT ISBLANK ( [Volume] ),\n    {por_dia} )", None, cr,
        "Espera extra da linha em cada dia do periodo, separada por ponto e virgula (vazio no dia sem dado). "
        "Alimenta a linha do cartao do carrossel.", oculta=True)
    add("Carrossel rede",
        'IF ( NOT ISBLANK ( [Volume] ),\n    CALCULATE (\n'
        '        FORMAT ( [Espera média], "0.000", "en-US" ) & ";" & FORMAT ( [Espera extra], "0.000", "en-US" ) & ";"\n'
        '            & FORMAT ( [Colados], "0.0000", "en-US" ) & ";" & FORMAT ( [Corte sem colagem], "0.0000", "en-US" ) & ";"\n'
        '            & FORMAT ( [Linhas na rede], "0" ) & ";" & FORMAT ( MIN ( dim_data[data] ), "dd/mm" ) & ";"\n'
        f'            & FORMAT ( MAX ( dim_data[data] ), "dd/mm" ) & "|" & {por_dia},\n'
        '        REMOVEFILTERS ( dim_linha ) ) )',
        None, cr, "Numeros da rede inteira para o cartao Rede inteira do carrossel: espera media; espera extra; "
        "colados; corte; linhas; inicio; fim | espera extra por dia. Ignora o filtro de linha.", oculta=True)

    # --- Cores (ocultas) -----------------------------------------------------------------
    c = "Cores"
    add("Cor do calor", escala_cor("[Espera extra]"), None, c, "Fundo do mapa de calor pela espera extra.", oculta=True)
    add("Letra do calor", escala_cor("[Espera extra]", letra=True), None, c, "Letra do mapa de calor.", oculta=True)
    add("Cor do calor top", escala_cor("[Calor top]"), None, c, "Fundo do mapa linha x faixa.", oculta=True)
    add("Letra do calor top", escala_cor("[Calor top]", letra=True), None, c, "Letra do mapa linha x faixa.",
        oculta=True)
    add("Cor do quadrante",
        "VAR x = [Colados]\nVAR y = [Espera extra]\n"
        "VAR rx = CALCULATE ( [Colados], REMOVEFILTERS ( dim_linha ) )\n"
        "VAR ry = CALCULATE ( [Espera extra], REMOVEFILTERS ( dim_linha ) )\n"
        f'RETURN\n    SWITCH ( TRUE (),\n        x >= rx && y >= ry, "{VERMELHO}",\n        y >= ry, "{AMBAR}",\n'
        f'        x >= rx, "{AZUL}",\n        "{APAGADO}" )',
        None, c, "Vermelho: muitos colados e muita espera; ambar: espera alta sem colagem; azul: colados sem "
        "espera alta; cinza: abaixo da rede nas duas.", oculta=True)
    add("Colados da rede", "CALCULATE ( [Colados], REMOVEFILTERS ( dim_linha ) )", "0.0%", c,
        "Referencia vertical do grafico de quadrantes.", oculta=True)
    add("Espera extra da rede", "CALCULATE ( [Espera extra], REMOVEFILTERS ( dim_linha ) )", "0.00", c,
        "Referencia horizontal do grafico de quadrantes.", oculta=True)

    # --- SVG ---------------------------------------------------------------------------
    sv = "SVG"
    w, h = 220, 44
    pontos = ("CONCATENATEX ( t,\n        FORMAT ( 4 + DIVIDE ( INT ( dim_data[data] - d0 ), MAX ( 1, INT ( d1 - d0 ) ) ) * "
              f"{w - 8}, \"0.0\", \"en-US\" ) & \",\" &\n        FORMAT ( {h - 5} - DIVIDE ( [@v], topo ) * {h - 10}, "
              "\"0.0\", \"en-US\" ),\n        \" \", dim_data[data], ASC )")
    add("Tendência",
        "VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_data[data] ), \"@v\", [Espera extra] ), NOT ISBLANK ( [@v] ) )\n"
        "VAR d0 = MINX ( t, dim_data[data] )\nVAR d1 = MAXX ( t, dim_data[data] )\n"
        "VAR topo = MAX ( 6, MAXX ( t, [@v] ) )\n"
        "VAR rede = CALCULATE ( [Espera extra], REMOVEFILTERS ( dim_linha ) )\n"
        f"VAR yr = FORMAT ( {h - 5} - DIVIDE ( rede, topo ) * {h - 10}, \"0.0\", \"en-US\" )\n"
        f"VAR pts = {pontos}\n"
        f"VAR ultimo = MAXX ( TOPN ( 1, t, dim_data[data], DESC ), [@v] )\n"
        f"VAR yu = FORMAT ( {h - 5} - DIVIDE ( ultimo, topo ) * {h - 10}, \"0.0\", \"en-US\" )\n"
        "RETURN\n    IF ( COUNTROWS ( t ) >= 2,\n        " + svg(
            f"\"<line x1='0' x2='{w}' y1='\" & yr & \"' y2='\" & yr & \"' stroke='{hexa(APAGADO)}' stroke-width='1' "
            f"stroke-dasharray='3 3'/>\" & \"<polyline points='\" & pts & \"' fill='none' stroke='{hexa(AMBAR)}' "
            f"stroke-width='2.2' stroke-linejoin='round'/>\" & \"<circle cx='{w - 4}' cy='\" & yu & \"' r='3.5' "
            f"fill='{hexa(AMBAR)}'/>\"", w, h) + " )",
        None, sv, "Mini grafico da espera extra por dia no periodo (escala de 0 a 6 min ou ao maximo da linha). "
        "Tracejado: a rede.", imagem=True)

    # --- Pontos (fato_paradas) ---------------------------------------------------------------
    pp = "Pontos"
    filtro_h = f"FILTER ( VALUES ( {P}[stop_id] ), CALCULATE ( {s(P, 'soma')} ) / 3600 >= {HORAS_MIN_PARADA} )"
    add("Ponto · espera extra", f"DIVIDE ( {s(P, 'dev2')}, {s(P, 'soma')} ) / 2 / 60", "0.00", pp,
        "Espera extra no ponto, ultimos 28 dias (min).")
    add("Ponto · espera regular", f"DIVIDE ( {s(P, 'soma2_n')}, {s(P, 'soma')} ) / 2 / 60", "0.00", pp,
        "Espera regular no ponto (min).")
    add("Ponto · colados", f"DIVIDE ( {s(P, 'colados')}, {s(P, 'n')} )", "0.0%", pp, "Colados no ponto.")
    add("Ponto · horas", f"{s(P, 'soma')} / 3600", "#,0", pp, "Horas de servico medidas no ponto.")
    add("Ponto · volume", f"{s(P, 'dev2')} / 2 / 60 / 3600", "#,0", pp, "Espera extra x horas no ponto.")
    add("Ponto · linhas", f"MAX ( {P}[linhas] )", "0", pp,
        "Linhas que passam no ponto (maior contagem entre tipo de dia e frequencia).")
    add("Ponto · mapa espera",
        f"IF ( HASONEVALUE ( {P}[stop_id] ) && [Ponto · horas] >= {HORAS_MIN_PARADA}, [Ponto · espera extra] )",
        "0.00", pp, f"Espera extra so dos pontos com {HORAS_MIN_PARADA} horas ou mais (mapa e ranking).")
    add("Ponto · latitude", f"IF ( NOT ISBLANK ( [Ponto · mapa espera] ), MAX ( {P}[stop_lat] ) )", "0.0000", pp,
        "Latitude do ponto.")
    add("Ponto · longitude", f"IF ( NOT ISBLANK ( [Ponto · mapa espera] ), MAX ( {P}[stop_lon] ) )", "0.0000", pp,
        "Longitude do ponto.")
    add("Pontos no mapa", f"COUNTROWS ( {filtro_h} )", "#,0", pp,
        f"Pontos com {HORAS_MIN_PARADA} horas de servico ou mais na janela.")
    add("Top 10 pontos parte",
        f"VAR t = ADDCOLUMNS ( {filtro_h}, \"@v\", [Ponto · volume] )\n"
        "RETURN DIVIDE ( SUMX ( TOPN ( 10, t, [@v], DESC ), [@v] ), SUMX ( t, [@v] ) )",
        "0.0%", pp, "Parte da espera extra dos pontos do mapa que esta nos 10 piores.")
    add("Ponto · espera extra rede",
        f"VAR t = {filtro_h}\nRETURN DIVIDE ( CALCULATE ( {s(P, 'dev2')}, t ), CALCULATE ( {s(P, 'soma')}, t ) ) / 2 / 60",
        "0.00", pp, "Espera extra media dos pontos do mapa.")
    add("Janela dos pontos",
        f'"DE " & FORMAT ( MIN ( {P}[janela_ini] ), "dd/mm" ) & " A " & FORMAT ( MAX ( {P}[janela_fim] ), "dd/mm" )',
        None, pp, "Janela de 28 dias dos pontos.")
    add("Ponto · parte",
        f"VAR v = IF ( NOT ISBLANK ( [Ponto · mapa espera] ), [Ponto · volume] )\n"
        f"VAR tot = CALCULATE ( SUMX ( {filtro_h}, [Ponto · volume] ), REMOVEFILTERS ( {P}[stop_id], {P}[stop_name] ) )\n"
        "RETURN DIVIDE ( v, tot )",
        "0.0%", pp, "Parte da espera extra dos pontos do mapa que esta no ponto.")
    add("Cor do ponto", escala_cor("[Ponto · mapa espera]"), None, "Cores", "Cor do ponto no mapa.", oculta=True)

    # --- Histograma -------------------------------------------------------------------------
    hh = "Histograma"
    add("Intervalos na classe", "SUM ( fato_hist[headways] )", "#,0", hh, "Intervalos medidos na classe.")
    add("% dos intervalos",
        "DIVIDE ( [Intervalos na classe], CALCULATE ( [Intervalos na classe], REMOVEFILTERS ( dim_classe ) ) )",
        "0.0%", hh, "Parte dos intervalos na classe (o histograma nao separa por linha).")
    add("Cor da classe", f'IF ( MAX ( dim_classe[classe] ) < 5, "{VERMELHO}", "{AZUL}" )', None, "Cores",
        "Vermelho nos colados (menos de 1/4 do medio).", oculta=True)

    # --- Previsao (fase 5) ----------------------------------------------------------------
    pv = "Previsão"
    teste = 'fato_previsao[conjunto] = "teste", ' + SEM_PERIODO
    add("Alertas", f"CALCULATE ( SUM ( fato_previsao[alertas] ), {teste} )", "#,0", pv,
        "Alertas no teste (fora da amostra). Ignora o filtro de periodo: o teste foi feito uma vez.")
    add("Acertos", f"CALCULATE ( SUM ( fato_previsao[acertos] ), {teste} )", "#,0", pv, "Alertas que chegaram colados.")
    add("Positivos", f"CALCULATE ( SUM ( fato_previsao[positivos] ), {teste} )", "#,0", pv, "Onibus que chegaram colados.")
    add("Exemplos", f"CALCULATE ( SUM ( fato_previsao[exemplos] ), {teste} )", "#,0", pv, "Passagens avaliadas.")
    add("Acerto dos alertas", "DIVIDE ( [Acertos], [Alertas] )", "0.0%", pv, "Precisao: dos alertas, quantos acertaram.")
    add("Colados avisados", "DIVIDE ( [Acertos], [Positivos] )", "0.0%", pv, "Revocacao: dos colados, quantos foram avisados.")
    add("Chance sem modelo", "DIVIDE ( [Positivos], [Exemplos] )", "0.0%", pv,
        "Chance de um onibus qualquer chegar colado (base).")
    add("Limiar", f"CALCULATE ( MAX ( fato_previsao[limiar] ), {teste} )", "0.000", pv, "Limiar fixado na validacao.")
    add("Janela do teste",
        f'VAR a = CALCULATE ( MIN ( fato_previsao[data_bh] ), {teste} )\n'
        f'VAR b = CALCULATE ( MAX ( fato_previsao[data_bh] ), {teste} )\n'
        'RETURN "TESTE DE " & FORMAT ( a, "dd/mm" ) & " A " & FORMAT ( b, "dd/mm" ) & "  ·  LIMIAR " & FORMAT ( [Limiar], "0.000" )',
        None, pv, "Janela e limiar do teste.")
    add("Alertas no dia", "CALCULATE ( SUM ( fato_previsao[alertas] ), fato_previsao[conjunto] = \"teste\", "
        "REMOVEFILTERS ( sel_periodo[periodo] ) )", "#,0", pv,
        "Alertas por dia do teste. Tira so a coluna do periodo: REMOVEFILTERS ( sel_periodo ) levaria junto o "
        "filtro de dim_data (tabela expandida).", oculta=True)
    add("Acertos no dia", "CALCULATE ( SUM ( fato_previsao[acertos] ), fato_previsao[conjunto] = \"teste\", "
        "REMOVEFILTERS ( sel_periodo[periodo] ) )", "#,0", pv, "Acertos por dia do teste.", oculta=True)

    add("Acerto no dia", "DIVIDE ( [Acertos no dia], [Alertas no dia] )", "0%", pv,
        "Acerto dos alertas em cada dia do teste.", oculta=True)
    add("Vezes a chance", "DIVIDE ( [Acerto dos alertas], [Chance sem modelo] )", "0.0", pv,
        "Quantas vezes o acerto dos alertas supera a chance de um onibus qualquer chegar colado.")
    add("Frase do modelo",
        '"Dos " & FORMAT ( [Alertas], "#,0" ) & " alertas, " & FORMAT ( [Acertos], "#,0" ) & " chegaram colados ("\n'
        '    & FORMAT ( [Acerto dos alertas], "0%" ) & "). Sem modelo, a chance de um ônibus chegar colado é de "\n'
        '    & FORMAT ( [Chance sem modelo], "0%" ) & ". Uso sugerido: lista de prioridade para o controle."',
        None, pv, "Leitura do teste do modelo, montada com as medidas.")

    # --- Qualidade ------------------------------------------------------------------------
    q = "Qualidade"
    add("Cobertura", "DIVIDE ( SUM ( fato_qualidade[headways_validos] ), SUM ( fato_qualidade[passagens] ) )", "0.0%",
        q, "Intervalos validos por passagem reconstruida (cobertura_passagens da Gold, reagregada).")
    add("Feed parado", "SUM ( fato_qualidade[headways_feed_parado] )", "#,0", q,
        "Intervalos que atravessam uma parada do feed (descartados).")
    add("Passagens", "SUM ( fato_qualidade[passagens] )", "#,0", q, "Passagens de onibus por ponto reconstruidas.")
    add("Feed parado %", "DIVIDE ( [Feed parado], SUM ( fato_qualidade[headways] ) )", "0.0%", q,
        "Intervalos descartados com o feed parado, sobre todos os intervalos reconstruidos.")
    add("Dias com feed parado", "COUNTROWS ( FILTER ( VALUES ( dim_data[data] ), [Feed parado] > 0 ) )", "0", q,
        "Dias com algum intervalo descartado por feed parado.")
    add("Dias com qualidade", "COUNTROWS ( FILTER ( VALUES ( dim_data[data] ), NOT ISBLANK ( [Passagens] ) ) )",
        "0", q, "Dias com medida de qualidade no recorte.")
    add("Viés texto", 'IF ( NOT ISBLANK ( [Viés de interpolação] ), FORMAT ( [Viés de interpolação], "0.000" ) & " min · "'
        ' & FORMAT ( [Viés de interpolação %], "0.0%" ) )', None, q, "Vies de interpolacao em minutos e em parte da espera extra.")

    # --- Simulador ---------------------------------------------------------------------------
    sm = "Simulador"
    add("Espaçamento", "SELECTEDVALUE ( sel_espacamento[espacamento], 0.5 )", "0%", sm,
        "Parte dos pares colados que o controle conseguiria espacar (padrao 50%).")
    add("Espera extra simulada",
        f"DIVIDE ( {s(L, 'dev2')} - [Espaçamento] * {s(L, 'reducao')}, {s(L, 'soma')} ) / 2 / 60", "0.00", sm,
        "Espera extra se essa parte dos pares colados passasse no meio do caminho.")
    add("Ganho por passageiro", "[Espera extra] - [Espera extra simulada]", "0.00", sm,
        "Minutos a menos de espera por ida ao ponto.")
    add("Ganho % da espera", "DIVIDE ( [Ganho por passageiro], [Espera média] )", "0.0%", sm,
        "Ganho sobre a espera media no ponto.")
    add("Espera média simulada", "[Espera regular] + [Espera extra simulada]", "0.00", sm, "Espera media simulada.")
    add("Volume poupado", f"[Espaçamento] * {s(L, 'reducao')} / 2 / 60 / 3600", "#,0", sm,
        "Volume de espera extra que sai (min x h).")
    add("Parte do ganho", "DIVIDE ( [Volume poupado], CALCULATE ( [Volume poupado], REMOVEFILTERS ( dim_linha ) ) )",
        "0.0%", sm, "Parte do ganho da rede que vem da linha.")
    add("Texto do simulador",
        '"Espaçando " & FORMAT ( [Espaçamento], "0%" ) & " dos pares colados, a espera extra cai de "\n'
        '    & FORMAT ( [Espera extra], "0.00" ) & " para " & FORMAT ( [Espera extra simulada], "0.00" ) & " min"',
        None, sm, "Frase do simulador.")

    # --- Onde agir: recomendacoes ------------------------------------------------------------
    oa = "Onde agir"
    add("Ganho sem colagem", "[Espera extra] * [Corte sem colagem]", "0.00", oa,
        "Minutos a menos por ida ao ponto se todos os pares colados fossem espacados (o simulador em 100%).")
    add("Espera extra da rede no recorte", "CALCULATE ( [Espera extra], REMOVEFILTERS ( dim_linha ) )", "0.00", oa,
        "Espera extra da rede inteira no recorte, sem o filtro de linha.")

    from paineis import medidas_html  # paineis le o layout do relatorio, que le as cores daqui
    for nome, dax, fmt, pasta, doc, op in medidas_html():
        add(nome, dax, fmt, pasta, doc, **op)
    return m


def tmdl_medidas() -> str:
    blocos = []
    for nome, dax, fmt, pasta, doc, op in medidas():
        linhas = [f"\t/// {doc}"]
        if "\n" in dax:
            linhas.append(f"\tmeasure {nome_tmdl(nome)} =")
            linhas.append(bloco(dax, 3))
        else:
            linhas.append(f"\tmeasure {nome_tmdl(nome)} = {dax}")
        if fmt:
            linhas.append(f"\t\tformatString: {fmt}")
        if op.get("imagem"):
            linhas.append("\t\tdataCategory: ImageUrl")
        if op.get("oculta"):
            linhas.append("\t\tisHidden")
        linhas += [f"\t\tdisplayFolder: {pasta}", f"\t\tlineageTag: {tag('medida', nome)}", ""]
        blocos.append("\n".join(linhas))
    return ("/// So medidas. Todo numero do relatorio sai daqui.\ntable _Medidas\n"
            f"\tlineageTag: {tag('tabela', '_Medidas')}\n\n" + "\n".join(blocos)
            + "\n\tcolumn x\n\t\tdataType: int64\n\t\tisHidden\n\t\tformatString: 0\n"
            + f"\t\tlineageTag: {tag('coluna', '_Medidas', 'x')}\n\t\tsummarizeBy: none\n\t\tsourceColumn: [x]\n\n"
            + "\t\tannotation SummarizationSetBy = User\n\n"
            + "\tpartition _Medidas = calculated\n\t\tmode: import\n\t\tsource = ROW ( \"x\", 0 )\n")


TABELAS = ["fato_linha", "fato_hist", "fato_paradas", "fato_qualidade", "fato_previsao", "dim_linha", "cargas",
           "eventos", "dim_data", "dim_faixa", "dim_tipo_dia", "dim_frequencia", "dim_classe", "sel_periodo",
           "sel_espacamento", "_Medidas"]


def arquivos_modelo(servidor: str, banco: str) -> dict[str, str]:
    """Caminho relativo a definition/ -> conteudo."""
    a = {
        "database.tmdl": "database\n\tcompatibilityLevel: 1606\n\n",
        "model.tmdl": (
            "model Model\n\tculture: pt-BR\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
            "\tsourceQueryCulture: pt-BR\n\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
            "annotation __PBI_TimeIntelligenceEnabled = 0\n\nannotation PBI_ProTooling = [\"DevMode\"]\n\n"
            "annotation PBI_QueryOrder = [\"ServidorPostgres\",\"BancoPostgres\","
            + ",".join(f'"{t}"' for t in TABELAS_BANCO) + ",\"cargas\"]\n\n"
            + "".join(f"ref table {nome_tmdl(t)}\n" for t in TABELAS) + "\nref cultureInfo pt-BR\n\n"),
        "expressions.tmdl": (
            "/// Servidor do Postgres do painel (endpoint do Neon). O valor real nao vai para o Git:\n"
            "/// o filtro powerbi/tools/git_censura.py troca pelo marcador.\n"
            f'expression ServidorPostgres = "{servidor}" meta [IsParameterQuery=true, Type="Text", '
            'IsParameterQueryRequired=true]\n'
            f"\tlineageTag: {tag('expressao', 'ServidorPostgres')}\n\n\tannotation PBI_ResultType = Text\n\n"
            "/// Banco do Postgres com o esquema radar.\n"
            f'expression BancoPostgres = "{banco}" meta [IsParameterQuery=true, Type="Text", '
            'IsParameterQueryRequired=true]\n'
            f"\tlineageTag: {tag('expressao', 'BancoPostgres')}\n\n\tannotation PBI_ResultType = Text\n\n"),
        "relationships.tmdl": tmdl_relacoes(),
        "cultures/pt-BR.tmdl": "cultureInfo pt-BR\n\n",
    }
    for t in TABELAS_BANCO:
        a[f"tables/{t}.tmdl"] = tmdl_dim_linha() if t == "dim_linha" else tmdl_tabela_banco(t)
    a["tables/cargas.tmdl"] = tmdl_cargas()
    for t in CALCULADAS:
        a[f"tables/{t}.tmdl"] = tmdl_calculada(t)
    a["tables/_Medidas.tmdl"] = tmdl_medidas()
    return a
