"""Grupos de headway e metricas da espera, num lugar so.

A analise (analise/calcular.py) e a exportacao para o banco do painel
(servico/exportar.py) usam estas funcoes, para que o painel mostre os mesmos
numeros do documento.

Grupo = linha, sentido, parada, dia e faixa horaria, com n >= 3 headways validos
e media m > 0. Por grupo, com H o headway:
  dev2       = soma de (H - m)^2
  excesso    = dev2 / (2 n m): espera estimada menos espera regular, a mesma
               conta do mart fct_headway_parada_faixa
  peso       = n m, o tempo coberto pelo grupo. Somar excesso x peso da a espera
               extra de um passageiro que chega ao acaso em qualquer parada e
               instante; excesso x peso = dev2 / 2.
  colado     = H < 0,25 m (bunching)
  reducao    = para cada colado H_i com o anterior H_{i-1} nao colado, igualar
               os dois (o onibus atrasado e o que vem colado nele) tira
               (H_{i-1} - H_i)^2 / 2 de dev2 sem mudar a media.
  vies       = a passagem e interpolada dentro do intervalo entre duas posicoes;
               com erro uniforme de largura intervalo_s / paradas_no_intervalo,
               a variancia por passagem e largura^2 / 12. O erro soma 2 x essa
               variancia ao E[(H-m)^2] e infla o excesso em var_passagem / m.

Todas as metricas sao razoes de somas. Por isso as SOMAS podem ser somadas de
novo em qualquer recorte (linha x dia x faixa no banco, depois so dia util, so
uma semana...) e a razao continua a mesma do calculo grupo a grupo. A espera
regular precisa de soma^2 / n por grupo, que nao sai de somas maiores: vai
pronta na coluna soma2_n.
"""
from pyspark.sql import Window as W, functions as F

COLADO = 0.25
MIN_HEADWAYS = 3  # var min_headways_parada do dbt
CLASSES_HIST = 80  # H/m em classes de 0,05; a classe 80 junta tudo de 4 para cima
CHAVE = ["route_id", "direction_id", "stop_id", "data_bh", "faixa_horaria", "ordem_faixa"]
CHAVE_LINHA = ["route_id", "direction_id", "data_bh", "faixa_horaria"]

# Somas reagregaveis, na ordem em que vao para o banco.
SOMAS = ["grupos", "n", "soma", "soma2_n", "dev2", "colados", "abaixo_60s", "reducao",
         "pares", "pulo_primeiro", "pulo_colado", "var_n"]


def calcular_grupos(ler, ini, fim):
    """Grupos e histograma de H/m entre ini e fim (datas de BH, inclusive).

    ler(caminho) devolve a tabela Delta da Gold. Cada grupo so depende do
    proprio dia, entao qualquer janela da o mesmo resultado para os dias dela.
    Devolve (grupos, hist): grupos ja com tipo_dia e alta_frequencia do mart de
    linha; hist por linha, sentido, dia, faixa e classe.
    """
    faixa = F.broadcast(ler("ref/faixa_horaria").select("hora_bh", "faixa_horaria", "ordem_faixa"))
    h = (ler("int/int_headways")
         .where(f"headway_valido and data_bh between '{ini}' and '{fim}'")
         .join(faixa, "hora_bh")
         .select(*CHAVE, "passagem_unix", "viagem_id", "stop_sequence", "headway_s"))
    g = W.partitionBy(*CHAVE)
    go = g.orderBy("passagem_unix", "viagem_id", "stop_sequence")
    h = (h.withColumn("n", F.count("*").over(g))
          .withColumn("m", F.avg("headway_s").over(g))
          .where(f"n >= {MIN_HEADWAYS} and m > 0")
          .withColumn("colado", F.col("headway_s") < COLADO * F.col("m"))
          .withColumn("ant", F.lag("headway_s").over(go))
          .withColumn("ant_colado", F.lag("colado").over(go)))
    par = F.col("colado") & F.col("ant").isNotNull() & ~F.col("ant_colado")
    grupos = h.groupBy(*CHAVE).agg(
        F.count("*").alias("n"),
        F.sum("headway_s").cast("double").alias("soma"),
        F.sum(F.pow(F.col("headway_s") - F.col("m"), 2)).alias("dev2"),
        F.sum(F.col("colado").cast("int")).alias("colados"),
        F.sum((F.col("headway_s") < 60).cast("int")).alias("abaixo_60s"),
        F.sum(F.when(par, F.pow(F.col("ant") - F.col("headway_s"), 2) / 2).otherwise(0)).alias("reducao"),
        F.sum(par.cast("int")).alias("pares"),
        F.sum((F.col("colado") & F.col("ant").isNull()).cast("int")).alias("pulo_primeiro"),
        F.sum((F.col("colado") & F.coalesce(F.col("ant_colado"), F.lit(False))).cast("int")).alias("pulo_colado"),
    )
    hist = (h.withColumn("classe", F.least(F.floor(F.col("headway_s") / F.col("m") / 0.05), F.lit(CLASSES_HIST)))
             .groupBy(*CHAVE_LINHA, "classe").count())

    # Variancia do erro de interpolacao, media por grupo.
    p = (ler("int/int_passagens")
         .where(f"motivo_exclusao is null and data_bh between '{ini}' and '{fim}'")
         .join(faixa, "hora_bh")
         .withColumn("var_p", F.pow(F.expr("try_divide(intervalo_s, paradas_no_intervalo)"), 2) / 12)
         .groupBy(*CHAVE).agg(F.avg("var_p").alias("var_passagem")))

    linha = ler("marts/fct_servico_linha_faixa").select(*CHAVE_LINHA, "tipo_dia", "alta_frequencia")
    grupos = grupos.join(linha, CHAVE_LINHA).join(p, CHAVE, "left")
    return grupos, hist.join(linha, CHAVE_LINHA)


def preparar(grupos):
    """Colunas por grupo que viram SOMAS: contador, soma^2/n e n x var_passagem."""
    return (grupos.withColumn("grupos", F.lit(1).cast("bigint"))
                  .withColumn("soma2_n", F.col("soma") * F.col("soma") / F.col("n"))
                  .withColumn("var_n", F.col("n") * F.col("var_passagem")))


def somar(df, chaves):
    """Soma as SOMAS por chaves. Entra grupo preparado ou ja somado; sai somado."""
    return df.groupBy(*chaves).agg(*[F.sum(c).alias(c) for c in SOMAS])


def dividir(a, b):
    """Spark com ANSI ligado da erro ao dividir por zero; aqui vira nulo."""
    return F.when(b != 0, a / b)


def metricas(df, chaves):
    """Metricas por recorte, de grupos preparados ou de somas ja reagregadas.

    Os minutos sao medias ponderadas pelo tempo coberto. As mesmas formulas
    estao em SQL (painel/consultas.py) e em DAX (powerbi/); os testes de
    conciliacao comparam as tres.
    """
    s = {c: F.col(c) for c in SOMAS}
    return somar(df, chaves).select(
        *chaves,
        s["grupos"].alias("grupos"),
        s["n"].alias("headways"),
        F.round(s["soma"] / 3600, 1).alias("horas"),
        F.round(s["soma2_n"] / 2 / s["soma"] / 60, 3).alias("regular_min"),
        F.round(s["dev2"] / 2 / s["soma"] / 60, 3).alias("excesso_min"),
        F.round(s["dev2"] / 2 / 60 / 3600, 1).alias("volume_min_h"),
        F.round(s["colados"] / s["n"], 4).alias("colados_pct"),
        F.round(s["abaixo_60s"] / s["n"], 4).alias("abaixo_60s_pct"),
        F.round(dividir(s["reducao"], s["dev2"]), 4).alias("reducao_pct"),
        s["pares"].alias("pares"),
        s["pulo_primeiro"].alias("pulo_primeiro"),
        s["pulo_colado"].alias("pulo_colado"),
        F.round(s["var_n"] / s["soma"] / 60, 3).alias("vies_min"),
        F.round(dividir(s["var_n"], s["dev2"] / 2), 4).alias("vies_pct"),
    )
