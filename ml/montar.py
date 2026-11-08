"""Fase 5: exemplos para prever bunching, a partir da Gold.

Roda no conteiner radar-ml:dev da VM de processamento:

    docker run --rm -v /home/ubuntu/radar:/app -v /home/ubuntu/ivy:/root/.ivy2.5.2 \
        radar-ml:dev python -m ml.montar

Um exemplo = o onibus B acabou de passar pela parada s (posicao stop_sequence da
viagem). Alvo: na parada s+N da mesma viagem, B chega colado no da frente, com a
definicao da Fase 4 (intervalo < 0,25 x media do grupo linha, sentido, parada,
dia, faixa; grupo com pelo menos 3 intervalos validos).

Populacao: dia util, linha e sentido de alta frequencia na faixa (media dos 14
dias anteriores ate 15 min, a mesma regra do mart, sem olhar o proprio dia),
intervalo valido em s e alvo definido em s+N.

Instante da decisao T = passagem_unix + intervalo_s (ver ml/features.py). O
lider do onibus da frente e o onibus de tras so entram se ja eram conhecidos em T.

Grava /app/dados/ml/exemplos (parquet por data_bh) e CSVs de conferencia em
/app/dados/ml/saida.

Roda um dia por vez. A primeira versao montava as seis semanas de uma vez e
encheu o disco da VM com mais de 17 GB de shuffle (08/11). Por isso, tres
etapas:
  1. por dia: base, vizinhos e features da viagem; grava os candidatos e tres
     agregados diarios pequenos (parada, linha, trecho);
  2. historico: as janelas de 14 dias rodam sobre os agregados;
  3. por dia: junta o historico aos candidatos (broadcast) e grava os exemplos.
Efeito colateral: vizinho na parada e viagem nao atravessam a meia-noite. O
primeiro onibus do dia fica sem lider e o ultimo sem onibus de tras.
"""
import csv
import os
import sys
from datetime import timedelta

sys.path.insert(0, "/app")
from silver.processar import sessao  # noqa: E402
from pyspark.sql import Window as W, functions as F  # noqa: E402

from ml import divisao  # noqa: E402

N = 10                 # paradas adiante
K = 5                  # trecho para tras (ritmo e onibus de tras)
COLADO = 0.25
MIN_HEADWAYS = 3       # var min_headways_parada do dbt
ALTA_FREQ_MIN = 15     # var alta_frequencia_min do dbt
HISTORICO_DIAS = 14
MIN_HIST = 10          # intervalos minimos no historico da parada
TRECHO_MAX_S = 3600

LEITURA_INI = divisao.INICIO - timedelta(days=HISTORICO_DIAS + 1)
INI, FIM = divisao.INICIO.isoformat(), divisao.FIM.isoformat()
G = "/app/dados/gold"
DADOS = "/app/dados/ml"
SAIDA = f"{DADOS}/saida"
GRUPO_DIA = ["route_id", "direction_id", "stop_id", "data_bh", "faixa_horaria"]

spark = None


def ler(caminho):
    return spark.read.format("delta").load(f"{G}/{caminho}")


def gravar_csv(df, nome):
    linhas = df.collect()
    with open(f"{SAIDA}/{nome}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(df.columns)
        w.writerows([list(r) for r in linhas])
    print(f"{nome}.csv: {len(linhas)} linhas", flush=True)


def dividir(a, b):
    """Spark com ANSI ligado da erro ao dividir por zero; aqui vira nulo."""
    return F.when(b != 0, a / b)


def historico(df, chaves, somas):
    """Somas dos HISTORICO_DIAS dias anteriores a cada data, so dia util.

    df tem uma linha por chaves + data_bh com as colunas de somas do proprio
    dia. A janela termina na vespera: o dia do exemplo nunca entra.
    """
    dia = F.datediff("data_bh", F.lit("1970-01-01"))
    janela = W.partitionBy(*chaves).orderBy(dia).rangeBetween(-HISTORICO_DIAS, -1)
    return df.select(*chaves, "data_bh", *[F.sum(s).over(janela).alias(f"{s}_hist") for s in somas])


def base(dia, feriados):
    """Intervalos de um dia, com o intervalo entre posicoes e o tipo do dia."""
    faixa = F.broadcast(ler("ref/faixa_horaria").select("hora_bh", "faixa_horaria"))
    periodo = f"data_bh = '{dia.isoformat()}'"
    h = (ler("int/int_headways").where(periodo)
         .select("route_id", "direction_id", "stop_id", "viagem_id", "stop_sequence", "vehicle_id",
                 "onibus_anterior", "data_bh", "hora_bh", "passagem_unix", "headway_s",
                 "headway_valido", "paradas_no_intervalo"))
    p = (ler("int/int_passagens").where(f"motivo_exclusao is null and {periodo}")
         .select("viagem_id", "stop_sequence", "data_bh", "intervalo_s", "letreiro"))
    dow = F.dayofweek("data_bh")
    b = (h.join(p, ["viagem_id", "stop_sequence", "data_bh"]).join(faixa, "hora_bh")
          .withColumn("disponivel_unix", F.col("passagem_unix") + F.col("intervalo_s"))
          .withColumn("dia_util", ~F.col("data_bh").isin(feriados) & dow.between(2, 6))
          .withColumn("h", F.when(F.col("headway_valido"), F.col("headway_s"))))

    # Alvo com a definicao da Fase 4: media do grupo no dia, so intervalos validos.
    g = W.partitionBy(*GRUPO_DIA)
    valido = F.col("headway_valido")
    b = (b.withColumn("n_dia", F.sum(valido.cast("int")).over(g))
          .withColumn("m_dia", dividir(F.sum(F.col("h")).over(g), F.col("n_dia")))
          .withColumn("rotulavel", valido & (F.col("n_dia") >= MIN_HEADWAYS) & (F.col("m_dia") > 0))
          .withColumn("colado", F.col("rotulavel") & (F.col("headway_s") < COLADO * F.col("m_dia"))))
    return b


PARADA = ["route_id", "direction_id", "stop_id", "faixa_horaria"]
LINHA = ["route_id", "direction_id", "faixa_horaria"]
TRECHO = ["route_id", "direction_id", "stop_5", "stop_id", "faixa_horaria"]


def agregados_dia(b):
    """Somas do dia que alimentam o historico dos dias seguintes (so dia util)."""
    util = b.where("dia_util and headway_valido")
    parada = (util.groupBy(*PARADA, "data_bh")
                  .agg(F.count("*").alias("n"), F.sum("headway_s").alias("soma")))
    linha = (util.where("rotulavel").groupBy(*LINHA, "data_bh")
                 .agg(F.count("*").alias("n"), F.sum(F.col("colado").cast("int")).alias("colados")))
    return parada, linha


def trecho_dia(x):
    """Tempo de s-5 ate s, somado por par de paradas e faixa (so dia util)."""
    return (x.where(f"dia_util and trecho_s > 0 and trecho_s <= {TRECHO_MAX_S}")
             .groupBy(*TRECHO, "data_bh")
             .agg(F.count("*").alias("n"), F.sum("trecho_s").alias("soma")))


def alta_frequencia():
    """Media diaria do mart (peso igual por parada) nos 14 dias anteriores."""
    servico = (ler("marts/fct_servico_linha_faixa")
               .where(f"tipo_dia = 'dia_util' and data_bh >= '{LEITURA_INI.isoformat()}'")
               .select(*LINHA, "data_bh", F.lit(1).alias("dias"), F.col("headway_medio_min").alias("soma_min")))
    return (historico(servico, LINHA, ["dias", "soma_min"])
            .select(*LINHA, "data_bh",
                    (F.col("soma_min_hist") / F.col("dias_hist") <= ALTA_FREQ_MIN).alias("alta_freq_hist")))


def historicos(agg):
    """Os tres historicos a partir dos agregados diarios gravados na etapa 1.

    O historico so existe nas datas em que a chave apareceu. Os exemplos sao de
    dias em que a linha rodou na parada, entao o join pela propria data basta.
    """
    parada = (historico(agg("parada"), PARADA, ["n", "soma"]).where(f"n_hist >= {MIN_HIST}")
              .select(*PARADA, "data_bh", (F.col("soma_hist") / F.col("n_hist")).alias("m_hist")))
    linha = (historico(agg("linha"), LINHA, ["n", "colados"])
             .select(*LINHA, "data_bh", dividir(F.col("colados_hist"), F.col("n_hist")).alias("taxa_colado_hist")))
    trecho = (historico(agg("trecho"), TRECHO, ["n", "soma"]).where(f"n_hist >= {MIN_HIST}")
              .select(*TRECHO, "data_bh", (F.col("soma_hist") / F.col("n_hist")).alias("trecho_hist")))
    return {"parada": parada, "linha": linha, "trecho": trecho}


def com_vizinhos(b):
    """Lider do onibus da frente e onibus de tras, na mesma parada."""
    na_parada = W.partitionBy("route_id", "direction_id", "stop_id").orderBy(
        "passagem_unix", "viagem_id", "stop_sequence")
    return (b.withColumn("lider_h", F.lag("h").over(na_parada))
             .withColumn("lider_disp", F.lag("disponivel_unix").over(na_parada))
             .withColumn("tras_h", F.lead("headway_s").over(na_parada))
             .withColumn("tras_disp", F.lead("disponivel_unix").over(na_parada))
             .withColumn("tras_valido", F.lead("headway_valido").over(na_parada)
                         & (F.lead("onibus_anterior").over(na_parada) == F.col("vehicle_id"))))


def na_viagem(col, k):
    """Valor da mesma viagem na posicao stop_sequence + k (nulo se nao houver)."""
    janela = W.partitionBy("viagem_id").orderBy("stop_sequence").rangeBetween(k, k)
    return F.max(col).over(janela)


def montar(b):
    T = F.col("disponivel_unix")
    x = (b.withColumn("h_1", na_viagem("h", -1))
          .withColumn("h_3", na_viagem("h", -3))
          .withColumn("h_5", na_viagem("h", -K))
          .withColumn("t_5", na_viagem("passagem_unix", -K))
          .withColumn("stop_5", na_viagem("stop_id", -K))
          .withColumn("tras_h_5", na_viagem("tras_h", -K))
          .withColumn("tras_disp_5", na_viagem("tras_disp", -K))
          .withColumn("tras_valido_5", na_viagem(F.col("tras_valido").cast("int"), -K))
          .withColumn("alvo_rotulavel", na_viagem(F.col("rotulavel").cast("int"), N))
          .withColumn("alvo_int", na_viagem(F.col("colado").cast("int"), N))
          .withColumn("h_alvo", na_viagem("headway_s", N))
          .withColumn("t_alvo", na_viagem("passagem_unix", N))
          .withColumn("stop_alvo", na_viagem("stop_id", N))
          .withColumn("faixa_alvo", na_viagem("faixa_horaria", N)))

    tras_conhecido = (F.col("tras_valido_5") == 1) & (F.col("tras_disp_5") <= T)
    x = (x.withColumn("trecho_s", F.col("passagem_unix") - F.col("t_5"))
          .withColumn("lider_conhecido", F.col("lider_disp") <= T)
          .withColumn("atras_s", F.when(tras_conhecido, F.col("tras_h_5"))
                                  .when(F.col("t_5").isNotNull(), T - F.col("t_5")))
          .withColumn("atras_censurado", F.when(F.col("t_5").isNotNull(), (~tras_conhecido).cast("int"))))
    return x


CANDIDATO = [
    "route_id", "direction_id", "stop_id", "viagem_id", "vehicle_id", "stop_sequence", "letreiro",
    "data_bh", "faixa_horaria", "passagem_unix", "disponivel_unix", "h", "h_1", "h_3", "h_5",
    "lider_h", "lider_conhecido", "atras_s", "atras_censurado", "trecho_s", "stop_5",
    "alvo_int", "h_alvo", "t_alvo", "stop_alvo", "faixa_alvo", "m_dia",
    "paradas_no_intervalo", "intervalo_s",
]


def candidatos(x, alta):
    """Exemplos possiveis do dia, antes do historico da parada e do trecho."""
    return (x.where("dia_util and h is not null and alvo_rotulavel = 1")
             .join(F.broadcast(alta), LINHA + ["data_bh"])
             .where("alta_freq_hist")
             .select(*CANDIDATO))


def final(x, hist, mapa):
    """Junta o historico ao candidato e calcula as features do modelo."""
    alvo = (hist["parada"].select(F.col("route_id"), F.col("direction_id"), F.col("data_bh"),
                                  F.col("stop_id").alias("stop_alvo"), F.col("faixa_horaria").alias("faixa_alvo"),
                                  F.col("m_hist").alias("m_hist_alvo")))
    x = (x.join(F.broadcast(hist["parada"]), PARADA + ["data_bh"])
          .join(F.broadcast(alvo), ["route_id", "direction_id", "data_bh", "stop_alvo", "faixa_alvo"], "left")
          .join(F.broadcast(hist["linha"]), LINHA + ["data_bh"], "left")
          .join(F.broadcast(hist["trecho"]), TRECHO + ["data_bh"], "left")
          .join(F.broadcast(mapa), ["route_id", "direction_id", "letreiro"], "left"))
    hora = F.from_utc_timestamp(F.timestamp_seconds("passagem_unix"), "America/Sao_Paulo")
    m = F.col("m_hist")
    conj = F.when(F.col("data_bh") <= divisao.FIM_TREINO.isoformat(), "treino") \
            .when(F.col("data_bh") <= divisao.FIM_VALIDACAO.isoformat(), "validacao") \
            .otherwise("teste")
    return (x.select(
                 "route_id", "direction_id", "stop_id", "viagem_id", "vehicle_id", "stop_sequence",
                 "data_bh", "faixa_horaria",
                 F.col("disponivel_unix").alias("decisao_unix"),
                 (F.col("alvo_int") == 1).alias("alvo"),
                 F.col("h_alvo"), F.col("m_dia"),
                 dividir(F.col("h_alvo"), F.col("m_hist_alvo")).alias("alvo_disfarcado"),
                 ((F.col("t_alvo") - F.col("disponivel_unix")) / 60).alias("minutos_ate_alvo"),
                 F.col("h").alias("h_s"),
                 dividir(F.col("h"), m).alias("h_rel"),
                 (F.col("h") - F.col("h_1")).alias("dh_1"),
                 (F.col("h") - F.col("h_3")).alias("dh_3"),
                 (F.col("h") - F.col("h_5")).alias("dh_5"),
                 F.when(F.col("lider_conhecido"), dividir(F.col("lider_h"), m)).alias("lider_rel"),
                 dividir(F.col("atras_s"), m).alias("atras_rel"),
                 F.col("atras_censurado"),
                 dividir(F.col("trecho_s"), F.col("trecho_hist")).alias("trecho_razao"),
                 (m / 60).alias("m_hist_min"),
                 F.col("taxa_colado_hist"),
                 (F.hour(hora) + F.minute(hora) / 60 + F.second(hora) / 3600).alias("hora"),
                 (F.dayofweek("data_bh") - 1).alias("dia_semana"),
                 F.col("stop_sequence").alias("posicao"),
                 dividir(F.col("stop_sequence"), F.col("ultima_posicao")).alias("frac_percurso"),
                 "paradas_no_intervalo", "intervalo_s",
                 conj.alias("conjunto"),
             ))


def conferencias(ex):
    """Contagens por conjunto e a taxa do alvo, com e sem colado ja em s."""
    ainda_nao = F.col("h_rel") >= COLADO
    r = ex.groupBy("conjunto").agg(
        F.countDistinct("data_bh").alias("dias"),
        F.count("*").alias("exemplos"),
        F.round(F.avg(F.col("alvo").cast("int")), 4).alias("taxa_alvo"),
        F.sum(ainda_nao.cast("int")).alias("exemplos_nao_colado_em_s"),
        F.round(F.avg(F.when(ainda_nao, F.col("alvo").cast("int"))), 4).alias("taxa_alvo_nao_colado_em_s"),
        F.countDistinct("route_id").alias("linhas"),
        F.round(F.expr("percentile_approx(minutos_ate_alvo, 0.5)"), 2).alias("minutos_ate_alvo_mediana"),
        F.round(F.avg("atras_censurado"), 4).alias("atras_censurado"),
        F.round(F.avg(F.col("lider_rel").isNull().cast("int")), 4).alias("lider_nulo"),
        F.round(F.avg(F.col("trecho_razao").isNull().cast("int")), 4).alias("trecho_nulo"),
    ).orderBy("conjunto")
    gravar_csv(r, "montagem_conjuntos")
    gravar_csv(ex.groupBy("data_bh").agg(F.count("*").alias("exemplos"),
                                         F.round(F.avg(F.col("alvo").cast("int")), 4).alias("taxa_alvo"))
                 .orderBy("data_bh"), "montagem_dias")


def esperar_janela_da_dag():
    """O Spark da DAG horaria roda entre :50 e :58 UTC; nao disputa com ele."""
    import time
    while 48 <= time.gmtime().tm_min < 59:
        time.sleep(30)


def gravar_dia(df, pasta, dia):
    df.drop("data_bh").write.mode("overwrite").parquet(f"{pasta}/data_bh={dia.isoformat()}")


def principal():
    global spark
    from pyspark import StorageLevel
    spark = sessao(os.environ.get("ML_MEMORIA", "5g"))
    os.makedirs(SAIDA, exist_ok=True)
    tmp = f"{DADOS}/tmp"
    feriados = [r[0] for r in ler("ref/feriados").select("data").collect()]
    alta = alta_frequencia().where(f"data_bh between '{INI}' and '{FIM}'").cache()
    mapa = (ler("int/int_mapa_parada").groupBy("route_id", "direction_id", "letreiro")
            .agg(F.max("stop_sequence").alias("ultima_posicao")).cache())

    # Etapa 1: um dia por vez, do inicio do historico ate o fim dos exemplos.
    for dia in divisao.dias(LEITURA_INI, divisao.FIM):
        esperar_janela_da_dag()
        x = montar(com_vizinhos(base(dia, feriados))).persist(StorageLevel.MEMORY_AND_DISK)
        parada, linha = agregados_dia(x)
        gravar_dia(parada, f"{tmp}/agg/parada", dia)
        gravar_dia(linha, f"{tmp}/agg/linha", dia)
        gravar_dia(trecho_dia(x), f"{tmp}/agg/trecho", dia)
        if dia >= divisao.INICIO:
            gravar_dia(candidatos(x, alta.where(F.col("data_bh") == F.lit(dia))), f"{tmp}/candidatos", dia)
        x.unpersist()
        print(f"etapa 1: {dia}", flush=True)

    # Etapa 2: historicos sobre os agregados (pequenos), gravados uma vez.
    hist = historicos(lambda nome: spark.read.parquet(f"{tmp}/agg/{nome}")
                      .withColumn("data_bh", F.col("data_bh").cast("date")))
    for nome, df in hist.items():
        df.where(f"data_bh between '{INI}' and '{FIM}'").write.mode("overwrite") \
          .partitionBy("data_bh").parquet(f"{tmp}/hist/{nome}")
    print("etapa 2: historicos", flush=True)

    # Etapa 3: um dia por vez, historico do dia em broadcast.
    for dia in divisao.dias(divisao.INICIO, divisao.FIM):
        esperar_janela_da_dag()
        cand = f"{tmp}/candidatos/data_bh={dia.isoformat()}"
        if not os.path.exists(cand):
            continue
        d = F.lit(dia)
        x = spark.read.parquet(cand).withColumn("data_bh", d)
        h = {n: spark.read.parquet(f"{tmp}/hist/{n}").withColumn("data_bh", F.col("data_bh").cast("date"))
                .where(F.col("data_bh") == d) for n in hist}
        gravar_dia(final(x, h, mapa), f"{DADOS}/exemplos", dia)
        print(f"etapa 3: {dia}", flush=True)

    conferencias(spark.read.parquet(f"{DADOS}/exemplos"))


if __name__ == "__main__":
    principal()
