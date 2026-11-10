"""Fase 4: espera extra por irregularidade e bunching, a partir da Gold.

Roda no conteiner radar-spark:dev da VM de processamento e grava CSVs pequenos
em SAIDA. Os graficos e o documento (docs/analise.md) saem desses CSVs.

    docker run --rm -v /home/ubuntu/radar:/app -v /home/ubuntu/ivy:/root/.ivy2.5.2 \
        radar-spark:dev python /app/analise/calcular.py [--reusar]

--reusar le a tabela de grupos gravada na rodada anterior e refaz so as somas.

As contas (grupos, dev2, colado, reducao, vies) estao em servico/metricas.py,
que o painel tambem usa.
"""
import csv
import os
import sys

sys.path.insert(0, "/app")
from silver.processar import sessao  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402
from servico.metricas import CHAVE, MIN_HEADWAYS, calcular_grupos as grupos_da_janela, metricas, preparar  # noqa: E402

INI, FIM = "2026-09-15", "2026-11-05"
G = "/app/dados/gold"
GTFS = "/app/dados/gtfs_estatico"
SAIDA = "/app/dados/analise"


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
    grupos, hist = grupos_da_janela(ler, INI, FIM)
    grupos.write.mode("overwrite").parquet(f"{SAIDA}/grupos.parquet")
    (hist.groupBy("tipo_dia", "alta_frequencia", "classe")
         .agg(F.sum("count").alias("headways"))
         .write.mode("overwrite").parquet(f"{SAIDA}/hist.parquet"))


def gtfs(nome):
    return spark.read.csv(f"{GTFS}/{nome}.txt", header=True, inferSchema=False)


def resumir():
    gr = preparar(spark.read.parquet(f"{SAIDA}/grupos.parquet")).cache()
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
