"""Fase 5: grava as previsoes de ml.treinar --teste como tabela Delta da Gold.

    docker run --rm -v /home/ubuntu/radar:/app -v /home/ubuntu/ivy:/root/.ivy2.5.2 \
        radar-ml:dev python -m ml.publicar

Uma linha por exemplo de validacao e teste: chave da passagem, probabilidade,
alerta, conjunto, limiar, versao do modelo e quando foi gerada. Treino fica
fora porque a previsao sobre ele e otimista; quem le usa o teste.
"""
import sys

sys.path.insert(0, "/app")
from silver.processar import sessao  # noqa: E402

DESTINO = "/app/dados/gold/ml/previsao_bunching"

if __name__ == "__main__":
    spark = sessao("2g")
    df = spark.read.parquet("/app/dados/ml/previsoes.parquet")
    (df.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
       .partitionBy("conjunto").save(DESTINO))
    r = spark.read.format("delta").load(DESTINO).groupBy("conjunto").count().orderBy("conjunto").collect()
    print({x["conjunto"]: x["count"] for x in r}, flush=True)
