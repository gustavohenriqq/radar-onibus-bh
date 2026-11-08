"""Ressalva 7 de docs/ml.md: a passagem do onibus da frente ja era conhecida na decisao?

    docker run --rm --memory 4g -e ML_MEMORIA=3g -v /home/ubuntu/radar:/app \
        -v /home/ubuntu/ivy:/root/.ivy2.5.2 -w /app radar-ml:dev python -m ml.medir_frente

h_s (e h_rel) usa a passagem do onibus da frente em s; dh_1, dh_3 e dh_5 usam a
passagem dele em s-1, s-3 e s-5. A montagem nao confere se essas passagens ja
existiam no instante da decisao. Aqui se mede, para cada exemplo gravado, se a
posicao de GPS que fecha a passagem do onibus da frente chegou depois da decisao.

A passagem fica conhecida na posicao seguinte do GPS, unix_anterior +
intervalo_s. A Gold nao guarda unix_anterior, entao a medida sai em dois limites:
  min: passagem_unix + 0,5 / paradas_no_intervalo x intervalo_s, o mais cedo
       possivel (passagem no ultimo ponto do intervalo);
  max: passagem_unix + intervalo_s, a mesma conta (conservadora) que a
       montagem usa para a decisao e para os vizinhos.
O valor real fica entre os dois.

O onibus da frente e a passagem anterior na parada (como em int_headways); o
exemplo so conta como identificado quando ela e do onibus_anterior. Grava
saida/frente.csv. Um dia por vez, fora da janela da DAG, como ml.montar.
"""
import csv
import os
import sys
from datetime import timedelta

sys.path.insert(0, "/app")
from silver.processar import sessao  # noqa: E402
from pyspark.sql import Window as W, functions as F  # noqa: E402

from ml import divisao  # noqa: E402
from ml.montar import esperar_janela_da_dag, na_viagem  # noqa: E402

G = "/app/dados/gold"
DADOS = "/app/dados/ml"
FAIXAS = [(0, 30), (30, 60), (60, 120), (120, 300), (300, None)]

spark = None


def ler(caminho):
    return spark.read.format("delta").load(f"{G}/{caminho}")


def passagens(dia):
    """Passagens da vespera e do dia, com o instante em que cada uma ficou conhecida."""
    periodo = f"data_bh between '{(dia - timedelta(days=1)).isoformat()}' and '{dia.isoformat()}'"
    h = (ler("int/int_headways").where(periodo)
         .select("route_id", "direction_id", "stop_id", "viagem_id", "stop_sequence", "vehicle_id",
                 "onibus_anterior", "data_bh", "passagem_unix"))
    p = (ler("int/int_passagens").where(f"motivo_exclusao is null and {periodo}")
         .select("viagem_id", "stop_sequence", "data_bh",
                 (F.col("passagem_unix") + 0.5 * F.col("intervalo_s") / F.col("paradas_no_intervalo")).alias("min"),
                 (F.col("passagem_unix") + F.col("intervalo_s")).alias("max")))
    na_parada = W.partitionBy("route_id", "direction_id", "stop_id").orderBy(
        "passagem_unix", "viagem_id", "stop_sequence")
    return (h.join(p, ["viagem_id", "stop_sequence", "data_bh"])
             .withColumn("frente_ok", F.lag("vehicle_id").over(na_parada) == F.col("onibus_anterior"))
             .withColumn("frente_min", F.lag("min").over(na_parada))
             .withColumn("frente_max", F.lag("max").over(na_parada))
             .where(F.col("data_bh") == F.lit(dia)))


def medir(dia):
    x = passagens(dia)
    for k in (1, 3, 5):
        for m in ("min", "max"):
            x = x.withColumn(f"{m}_{k}", na_viagem(f"frente_{m}", -k))
    ex = (spark.read.parquet(f"{DADOS}/exemplos/data_bh={dia.isoformat()}")
          .select("viagem_id", "stop_sequence", "decisao_unix", "conjunto", "dh_1", "dh_3", "dh_5"))
    x = ex.join(x.drop("route_id", "direction_id", "stop_id", "vehicle_id", "onibus_anterior",
                       "data_bh", "passagem_unix", "min", "max"),
                ["viagem_id", "stop_sequence"], "left")
    T = F.col("decisao_unix")
    soma = lambda c: F.sum(F.coalesce(c, F.lit(False)).cast("int"))  # noqa: E731
    medidas = [F.count("*").alias("exemplos"), soma(F.col("frente_ok")).alias("frente_identificada")]
    for m in ("min", "max"):
        tarde_s = F.coalesce(F.col(f"frente_{m}") > T, F.lit(False))
        tarde_dh = F.lit(False)
        for k in (1, 3, 5):
            tarde_dh = tarde_dh | F.coalesce(F.col(f"dh_{k}").isNotNull() & (F.col(f"{m}_{k}") > T), F.lit(False))
        medidas += [soma(tarde_s).alias(f"tarde_s_{m}"), soma(tarde_dh).alias(f"tarde_dh_{m}"),
                    soma(tarde_s | tarde_dh).alias(f"tarde_qualquer_{m}")]
    # Quanto depois da decisao a passagem da frente em s chegou, pela regra da montagem.
    atraso = F.col("frente_max") - T
    medidas += [soma((atraso > a) & (atraso <= b if b else F.lit(True))).alias(f"atraso_{a}_{b or 'mais'}")
                for a, b in FAIXAS]
    return x.groupBy("conjunto").agg(*medidas).collect()


def principal():
    global spark
    spark = sessao(os.environ.get("ML_MEMORIA", "5g"))
    total = {}
    for dia in divisao.dias(divisao.INICIO, divisao.FIM):
        if not os.path.exists(f"{DADOS}/exemplos/data_bh={dia.isoformat()}"):
            continue
        esperar_janela_da_dag()
        for r in medir(dia):
            acc = total.setdefault(r["conjunto"], {})
            for c, v in r.asDict().items():
                if c != "conjunto":
                    acc[c] = acc.get(c, 0) + (v or 0)
        print(f"medido: {dia}", flush=True)

    ordem = ["treino", "validacao", "teste"]
    colunas = list(next(iter(total.values())).keys())
    linhas = [[c] + [total[c][k] for k in colunas] for c in ordem if c in total]
    linhas.append(["todos"] + [sum(total[c][k] for c in total) for k in colunas])
    with open(f"{DADOS}/saida/frente.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["conjunto"] + colunas)
        w.writerows(linhas)
    for l in linhas:
        print(dict(zip(["conjunto"] + colunas, l)), flush=True)


if __name__ == "__main__":
    principal()
