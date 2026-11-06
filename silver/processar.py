"""Job da Silver: contêineres horarios do Bronze -> tabela Delta deduplicada.

Uso:
    python -m silver.processar --de 2026-09-15 --ate 2026-09-21
        [--bronze DIR] [--destino CAMINHO] [--sem-optimize] [--vacuum]
    python -m silver.processar --hora 2026-11-05T14 --sem-optimize

Processa dia a dia, em horario de BH, ou uma hora UTC so (o que o Airflow faz a
cada hora fechada). Para cada dia ou hora:

1. le as horas UTC do dia (silver/janela.py), ou a hora pedida, e decodifica em
   paralelo;
2. deduplica por (vehicle_id, vehicle_ts), a chave do proprio feed, e nao pelo
   horario da coleta. Medido: 40,1% dos registros no pico sao repeticao;
3. faz MERGE na tabela Delta. Idempotente: rodar o mesmo dia de novo nao muda
   nada, porque so atualiza quando a copia nova foi vista numa coleta anterior
   a que ja esta gravada;
4. roda OPTIMIZE nas particoes tocadas: MERGE diario gera arquivos pequenos, o
   mesmo problema que a compactacao da fase 1 resolveu no Bronze.

O destino e uma pasta local: em producao, o disco da VM de processamento.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

from compactacao.horas import Hora
from silver.janela import BH, dias, hora_utc, horas_utc_do_dia

log = logging.getLogger("silver")

CHAVE = ("vehicle_id", "vehicle_ts")


def schema():
    from pyspark.sql import types as T
    ts, s = T.TimestampType(), T.StringType()
    return T.StructType([
        T.StructField("coleta_ts", ts, False),
        T.StructField("feed_ts", ts),
        T.StructField("entity_id", s),
        T.StructField("vehicle_id", s),
        T.StructField("vehicle_label", s),
        T.StructField("vehicle_ts", ts),
        T.StructField("trip_id", s),
        T.StructField("route_id", s),
        T.StructField("direction_id", T.IntegerType()),
        T.StructField("start_date", s),
        T.StructField("start_time", s),
        T.StructField("latitude", T.DoubleType()),
        T.StructField("longitude", T.DoubleType()),
        T.StructField("bearing", T.FloatType()),
        T.StructField("speed", T.FloatType()),
        T.StructField("current_stop_sequence", T.IntegerType()),
        T.StructField("current_status", T.IntegerType()),
        T.StructField("stop_id", s),
    ])


def sessao(memoria: str = "4g"):
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession
    builder = (
        SparkSession.builder.appName("radar-silver")
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        # Tudo em UTC dentro do Spark. A conversao para BH acontece uma vez, de
        # forma explicita, na coluna data_bh; nunca pelo fuso da maquina.
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.driver.memory", memoria)
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


def _linhas_do_conteiner(caminho: str):
    # Roda nos workers: importa aqui para nao depender do estado do driver.
    from compactacao import formato
    from silver.decodificar import decodificar
    for nome, protobuf in formato.ler(Path(caminho)):
        yield from decodificar(nome, protobuf)


def decodificados(spark, conteineres: list[Path]):
    """Um contêiner por particao: cada hora e decodificada em paralelo."""
    rdd = spark.sparkContext.parallelize([str(c) for c in conteineres], max(1, len(conteineres)))
    return spark.createDataFrame(rdd.flatMap(_linhas_do_conteiner), schema())


def deduplicar(df):
    """Uma linha por (vehicle_id, vehicle_ts), com a primeira coleta que a viu.

    min() sobre um struct que comeca pela coleta escolhe a observacao mais
    antiga, e e deterministico: rodar de novo escolhe a mesma linha.
    """
    from pyspark.sql import functions as F
    outras = [c for c in df.columns if c not in CHAVE]
    return (
        df.filter(F.col("vehicle_id").isNotNull() & F.col("vehicle_ts").isNotNull())
        .groupBy(*CHAVE)
        .agg(F.min(F.struct(*outras)).alias("r"))
        .select(*CHAVE, "r.*")
        .withColumnRenamed("coleta_ts", "primeira_coleta_ts")
        # Data do evento (vehicle_ts), nao da coleta: uma posicao das 23:59:50
        # coletada as 00:00:30 pertence ao dia anterior.
        .withColumn("data_bh", F.to_date(F.from_utc_timestamp("vehicle_ts", str(BH))))
    )


def gravar(spark, unicos, destino: str) -> dict:
    from delta.tables import DeltaTable
    if not DeltaTable.isDeltaTable(spark, destino):
        unicos.limit(0).write.format("delta").partitionBy("data_bh").save(destino)
    datas = sorted(r.data_bh for r in unicos.select("data_bh").distinct().collect())
    if not datas:
        return {"inseridas": 0, "atualizadas": 0, "datas": []}
    # data_bh na condicao: o MERGE so le as particoes que podem casar, em vez
    # da tabela inteira.
    em = ", ".join(f"DATE'{d}'" for d in datas)
    (
        DeltaTable.forPath(spark, destino).alias("t")
        .merge(unicos.alias("s"),
               f"t.data_bh IN ({em}) AND t.vehicle_id = s.vehicle_id AND t.vehicle_ts = s.vehicle_ts")
        # A mesma posicao pode aparecer em duas janelas (coleta das 02:59:30 e
        # das 03:00:00 UTC). Fica a primeira coleta, em qualquer ordem de
        # processamento, e reprocessar nao muda nada.
        .whenMatchedUpdateAll(condition="s.primeira_coleta_ts < t.primeira_coleta_ts")
        .whenNotMatchedInsertAll()
        .execute()
    )
    m = DeltaTable.forPath(spark, destino).history(1).collect()[0]["operationMetrics"]
    return {
        "inseridas": int(m.get("numTargetRowsInserted", 0)),
        "atualizadas": int(m.get("numTargetRowsUpdated", 0)),
        "datas": [str(d) for d in datas],
    }


def otimizar(spark, destino: str, datas: list[str]) -> None:
    if datas:
        em = ", ".join(f"'{d}'" for d in datas)
        spark.sql(f"OPTIMIZE delta.`{destino}` WHERE data_bh IN ({em}) ZORDER BY (route_id)")


def limpar_versoes(spark, destino: str, horas: int = 168) -> None:
    """Apaga arquivos que a tabela atual nao usa e sao mais velhos que `horas`.

    Cada MERGE seguido de OPTIMIZE deixa para tras os arquivos que substituiu, e
    eles continuam no disco por causa do historico de versoes do Delta.
    """
    spark.sql(f"VACUUM delta.`{destino}` RETAIN {horas} HOURS")


def processar_dia(spark, dia: date, dir_horario: Path, destino: str, optimize: bool = True) -> dict:
    return {"dia": str(dia), **processar_horas(spark, horas_utc_do_dia(dia), dir_horario, destino, optimize)}


def processar_horas(spark, horas: list[Hora], dir_horario: Path, destino: str, optimize: bool = True) -> dict:
    """MERGE de um conjunto de horas. A chave e do feed, entao uma hora sozinha
    da o mesmo resultado que o dia inteiro: a copia que aparece em duas horas
    fica com a primeira coleta, em qualquer ordem."""
    t0 = time.perf_counter()
    conteineres = [h.conteiner(dir_horario) for h in horas]
    presentes = [c for c in conteineres if c.exists()]
    ausentes = [f"{h.dt} {h.hh}" for h, c in zip(horas, conteineres) if not c.exists()]

    brutos = decodificados(spark, presentes).persist()
    n_brutos = brutos.count()
    unicos = deduplicar(brutos).persist()
    n_unicos = unicos.count()
    resultado = gravar(spark, unicos, destino)
    if optimize:
        otimizar(spark, destino, resultado["datas"])
    brutos.unpersist()
    unicos.unpersist()
    return {
        "horas": len(presentes),
        "horas_ausentes": ausentes,
        "registros": n_brutos,
        "unicos": n_unicos,
        "duplicacao_pct": round(100 * (1 - n_unicos / n_brutos), 1) if n_brutos else None,
        "inseridas": resultado["inseridas"],
        "atualizadas": resultado["atualizadas"],
        "datas": resultado["datas"],
        "segundos": round(time.perf_counter() - t0, 1),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bronze -> Silver em Delta, por janela de datas em BH")
    p.add_argument("--de", type=date.fromisoformat)
    p.add_argument("--ate", type=date.fromisoformat)
    p.add_argument("--hora", type=hora_utc, help="uma hora UTC, AAAA-MM-DDTHH, em vez de --de/--ate")
    p.add_argument("--bronze", type=Path, default=Path(os.environ.get("SILVER_BRONZE_DIR", "dados")),
                   help="pasta que contem bronze_horario/ (padrao: ./dados)")
    p.add_argument("--destino", default=os.environ.get("SILVER_DESTINO", "dados/silver/posicoes"),
                   help="pasta da tabela Delta")
    p.add_argument("--sem-optimize", action="store_true")
    p.add_argument("--vacuum", action="store_true", help="no fim, apaga versoes antigas (mais de 7 dias)")
    args = p.parse_args(argv)
    if bool(args.hora) == bool(args.de or args.ate) or (args.de is None) != (args.ate is None):
        p.error("use --hora, ou --de e --ate")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # OPTIMIZE delta.`...` so aceita caminho absoluto.
    destino = str(Path(args.destino).resolve())

    spark = sessao()
    spark.sparkContext.setLogLevel("WARN")
    # Absoluto tambem: os workers Python do Spark nao herdam a pasta corrente do
    # driver, entao um caminho relativo so funcionaria por coincidencia.
    dir_horario = args.bronze.resolve() / "bronze_horario" / "vehicle_positions"
    falhas = 0
    if args.hora:
        lotes = [(f"{args.hora.dt}T{args.hora.hh}", lambda: processar_horas(
            spark, [args.hora], dir_horario, destino, not args.sem_optimize))]
    else:
        lotes = [(str(d), lambda d=d: processar_dia(spark, d, dir_horario, destino, not args.sem_optimize))
                 for d in dias(args.de, args.ate)]
    for nome, rodar in lotes:
        try:
            r = rodar()
            log.info(json.dumps({"lote": nome, **r}, ensure_ascii=False))
            if args.hora and not r["horas"]:
                # Quem pede uma hora espera que ela exista: o Airflow so chama depois
                # de ver o conteiner no bucket. Sem ele, e falha, nao "zero linhas".
                raise FileNotFoundError(f"conteiner da hora {nome} nao encontrado")
        except Exception as e:
            falhas += 1
            log.exception(json.dumps({"lote": nome, "erro": str(e)[:300]}))
    if args.vacuum and not falhas:
        limpar_versoes(spark, destino)
    spark.stop()
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
