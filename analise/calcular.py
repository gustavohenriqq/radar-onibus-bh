"""Fase 4: espera extra por irregularidade e bunching, a partir da Gold.

Roda no conteiner radar-spark:dev da VM de processamento e grava CSVs pequenos
em SAIDA. Os graficos e o documento (docs/analise.md) saem desses CSVs.

    docker run --rm -v /home/ubuntu/radar:/app -v /home/ubuntu/ivy:/root/.ivy2.5.2 \
        radar-spark:dev python /app/analise/calcular.py [--reusar]

--reusar le a tabela de grupos gravada na rodada anterior e refaz so as somas.

Contas, por grupo (linha, sentido, parada, dia, faixa horaria), com H o headway,
n a quantidade e m a media:
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
"""
import csv
import os
import sys

sys.path.insert(0, "/app")
from silver.processar import sessao  # noqa: E402
from pyspark.sql import Window as W, functions as F  # noqa: E402

INI, FIM = "2026-09-15", "2026-11-05"
COLADO = 0.25
MIN_HEADWAYS = 3  # var min_headways_parada do dbt
G = "/app/dados/gold"
GTFS = "/app/dados/gtfs_estatico"
SAIDA = "/app/dados/analise"
CHAVE = ["route_id", "direction_id", "stop_id", "data_bh", "faixa_horaria", "ordem_faixa"]


def ler(caminho):
    return spark.read.format("delta").load(f"{G}/{caminho}")


def gravar(df, nome, ordem=None):
    """CSV pequeno, gravado com o modulo csv para nao depender de pandas."""
    if ordem:
        df = df.orderBy(*ordem)
    linhas = df.collect()
    with open(f"{SAIDA}/{nome}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(df.columns)
        w.writerows([list(r) for r in linhas])
    print(f"{nome}.csv: {len(linhas)} linhas", flush=True)


def calcular_grupos():
    faixa = F.broadcast(ler("ref/faixa_horaria").select("hora_bh", "faixa_horaria", "ordem_faixa"))
    h = (ler("int/int_headways")
         .where(f"headway_valido and data_bh between '{INI}' and '{FIM}'")
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
    # Histograma de H/m, em classes de 0,05 ate 4 (a ultima junta o resto).
    hist = (h.withColumn("classe", F.least(F.floor(F.col("headway_s") / F.col("m") / 0.05), F.lit(80)))
             .groupBy("route_id", "direction_id", "data_bh", "faixa_horaria", "classe").count())

    # Variancia do erro de interpolacao, media por grupo.
    p = (ler("int/int_passagens")
         .where(f"motivo_exclusao is null and data_bh between '{INI}' and '{FIM}'")
         .join(faixa, "hora_bh")
         .withColumn("var_p", F.pow(F.expr("try_divide(intervalo_s, paradas_no_intervalo)"), 2) / 12)
         .groupBy(*CHAVE).agg(F.avg("var_p").alias("var_passagem")))

    linha = ler("marts/fct_servico_linha_faixa").select(
        "route_id", "direction_id", "data_bh", "faixa_horaria", "tipo_dia", "alta_frequencia")
    chave_linha = ["route_id", "direction_id", "data_bh", "faixa_horaria"]
    grupos = grupos.join(linha, chave_linha).join(p, CHAVE, "left")
    grupos.write.mode("overwrite").parquet(f"{SAIDA}/grupos.parquet")
    (hist.join(linha, chave_linha).groupBy("tipo_dia", "alta_frequencia", "classe")
         .agg(F.sum("count").alias("headways"))
         .write.mode("overwrite").parquet(f"{SAIDA}/hist.parquet"))


def dividir(a, b):
    """Spark com ANSI ligado da erro ao dividir por zero; aqui vira nulo."""
    return F.when(b != 0, a / b)


def metricas(df, chaves):
    """Somas por recorte; os minutos sao medias ponderadas pelo tempo coberto."""
    return df.groupBy(*chaves).agg(
        F.count("*").alias("grupos"),
        F.sum("n").alias("headways"),
        F.round(F.sum("soma") / 3600, 1).alias("horas"),
        F.round(F.sum(F.col("soma") * F.col("soma") / F.col("n")) / 2 / F.sum("soma") / 60, 3).alias("regular_min"),
        F.round(F.sum("dev2") / 2 / F.sum("soma") / 60, 3).alias("excesso_min"),
        F.round(F.sum("dev2") / 2 / 60 / 3600, 1).alias("volume_min_h"),
        F.round(F.sum("colados") / F.sum("n"), 4).alias("colados_pct"),
        F.round(F.sum("abaixo_60s") / F.sum("n"), 4).alias("abaixo_60s_pct"),
        F.round(dividir(F.sum("reducao"), F.sum("dev2")), 4).alias("reducao_pct"),
        F.sum("pares").alias("pares"),
        F.sum("pulo_primeiro").alias("pulo_primeiro"),
        F.sum("pulo_colado").alias("pulo_colado"),
        F.round(F.sum(F.col("n") * F.col("var_passagem")) / F.sum("soma") / 60, 3).alias("vies_min"),
        F.round(dividir(F.sum(F.col("n") * F.col("var_passagem")), F.sum("dev2") / 2), 4).alias("vies_pct"),
    )


def gtfs(nome):
    return spark.read.csv(f"{GTFS}/{nome}.txt", header=True, inferSchema=False)


def resumir():
    gr = spark.read.parquet(f"{SAIDA}/grupos.parquet").cache()
    tipo = ["tipo_dia", "alta_frequencia"]

    gravar(metricas(gr, tipo), "rede", tipo)
    gravar(metricas(gr, tipo + ["ordem_faixa", "faixa_horaria"]), "rede_faixa", tipo + ["ordem_faixa"])

    # O route_id do feed em tempo real e o numero da linha, que no GTFS estatico
    # e route_short_name (o route_id do GTFS e um codigo interno). Conferido em
    # 07/11: as 311 linhas da janela batem por route_short_name, nenhuma por route_id.
    rotas = gtfs("routes").select("route_short_name", "route_long_name").withColumn(
        "route_id", F.col("route_short_name"))
    gravar(metricas(gr, tipo + ["route_id"]).join(rotas, "route_id", "left"), "linhas", tipo + ["route_id"])
    gravar(metricas(gr.where("tipo_dia = 'dia_util' and alta_frequencia"), ["route_id", "ordem_faixa", "faixa_horaria"])
           .join(rotas, "route_id", "left"), "linhas_faixa_dia_util", ["route_id", "ordem_faixa"])

    pontos = gtfs("stops").select("stop_id", "stop_name", "stop_lat", "stop_lon")
    por_parada = metricas(gr, tipo + ["stop_id"]).join(
        gr.groupBy(*tipo, "stop_id").agg(F.countDistinct("route_id").alias("linhas")), tipo + ["stop_id"])
    gravar(por_parada.join(pontos, "stop_id", "left"), "paradas", tipo + ["stop_id"])

    hist = spark.read.parquet(f"{SAIDA}/hist.parquet")
    gravar(hist, "hist_h_sobre_media", tipo + ["classe"])

    conferir(gr)


def conferir(gr):
    """Segunda conta: o mesmo numero por outro caminho."""
    # 1. Grupo a grupo contra o mart fct_headway_parada_faixa.
    mart = (ler("marts/fct_headway_parada_faixa")
            .where(f"data_bh between '{INI}' and '{FIM}' and headways >= {MIN_HEADWAYS} and headway_medio_min > 0"))
    j = (gr.withColumn("excesso_g", F.col("dev2") / 2 / F.col("soma") / 60)
           .join(mart, CHAVE, "full_outer"))
    um = j.agg(
        F.sum(F.col("n").isNull().cast("int")).alias("so_no_mart"),
        F.sum(F.col("headways").isNull().cast("int")).alias("so_no_script"),
        F.max(F.abs(F.col("n") - F.col("headways"))).alias("max_dif_headways"),
        F.max(F.abs(F.col("excesso_g") - F.col("espera_excesso_min"))).alias("max_dif_excesso_min"),
    )
    gravar(um, "conferencia_grupos")

    # 2. Media com peso igual por parada contra o mart de linha.
    lin = (gr.withColumn("excesso_g", F.col("dev2") / 2 / F.col("soma") / 60)
             .groupBy("route_id", "direction_id", "data_bh", "faixa_horaria")
             .agg(F.avg("excesso_g").alias("meu"), F.sum("n").alias("meus_headways")))
    ml = ler("marts/fct_servico_linha_faixa").where(f"data_bh between '{INI}' and '{FIM}'")
    dois = (lin.join(ml, ["route_id", "direction_id", "data_bh", "faixa_horaria"], "full_outer")
               .agg(F.sum(F.col("meu").isNull().cast("int")).alias("so_no_mart"),
                    F.sum(F.col("espera_excesso_min").isNull().cast("int")).alias("so_no_script"),
                    F.max(F.abs(F.col("meu") - F.col("espera_excesso_min"))).alias("max_dif_excesso_min"),
                    F.max(F.abs(F.col("meus_headways") - F.col("headways"))).alias("max_dif_headways")))
    gravar(dois, "conferencia_linhas")
    # Media simples do mart de linha (o numero da exploracao), para comparar os pesos.
    gravar(ml.groupBy("tipo_dia", "alta_frequencia").agg(
        F.count("*").alias("linha_dia_faixa"),
        F.round(F.avg("espera_regular_min"), 3).alias("regular_min_peso_igual"),
        F.round(F.avg("espera_excesso_min"), 3).alias("excesso_min_peso_igual")),
        "rede_peso_igual", ["tipo_dia", "alta_frequencia"])

    # 3. Headways validos por dia contra fct_qualidade_diaria (inclui grupos com n < 3).
    hv = (ler("int/int_headways").where(f"headway_valido and data_bh between '{INI}' and '{FIM}'")
          .groupBy("data_bh").count())
    q = ler("marts/fct_qualidade_diaria").where(f"data_bh between '{INI}' and '{FIM}'")
    tres = hv.join(q, "data_bh", "full_outer").agg(
        F.count("*").alias("dias"),
        F.sum(F.col("count").isNull().cast("int")).alias("so_no_mart"),
        F.max(F.abs(F.col("count") - F.col("headways_validos"))).alias("max_dif_headways_validos"),
        F.sum("count").alias("headways_validos"))
    gravar(tres, "conferencia_qualidade")


if __name__ == "__main__":
    os.makedirs(SAIDA, exist_ok=True)
    spark = sessao("3g")
    spark.sparkContext.setLogLevel("ERROR")
    if "--reusar" not in sys.argv:
        calcular_grupos()
    resumir()
