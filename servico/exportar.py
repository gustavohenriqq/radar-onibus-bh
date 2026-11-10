"""Exporta agregados da Gold para o Postgres do painel (Neon).

Roda no conteiner radar-spark:dev, uma vez por dia, quando o dia de BH fecha
(tarefa exportar_servico da DAG radar_horario):

    docker run --rm -v /home/ubuntu/radar:/app -v /home/ubuntu/ivy:/root/.ivy2.5.2 \
        radar-spark:dev python -m servico.exportar [--ate AAAA-MM-DD] [--dias 3 | --tudo]

As marts tem cerca de 2 GB e o Neon gratis tem 0,5 GB, entao o banco recebe
somas reagregaveis (servico/metricas.py), nao as marts:

  linha_dia_faixa   linha x sentido x dia x faixa, com as SOMAS. Recalcula os
                    ultimos --dias dias (o mais recente pode ter sido refeito
                    pela Gold) ou tudo desde DATA_INICIO.
  hist_dia          histograma de H/m por dia, tipo de dia e alta frequencia
  paradas_28d       parada x tipo de dia x alta frequencia nos 28 dias ate --ate,
                    com nome e coordenadas do GTFS (para o mapa)
  qualidade_diaria  copia de marts/fct_qualidade_diaria
  ml_resumo         alertas e acertos do modelo de bunching por dia e linha
  linhas            nome de cada linha (routes.txt)
  cargas            uma linha por exportacao, para o painel dizer a data

Tudo entra numa transacao so: apaga a janela, copia, confere as contagens e
so entao confirma. Se algo falhar no meio, o banco fica como estava.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

DATA_INICIO = date(2026, 9, 15)  # primeiro dia cheio da Gold
DIAS_PARADAS = 28
G = "/app/dados/gold"
GTFS = "/app/dados/gtfs_estatico"
ESQUEMA = "radar"

SOMAS_DDL = """
    grupos bigint not null, n bigint not null, soma double precision not null,
    soma2_n double precision not null, dev2 double precision not null,
    colados bigint not null, abaixo_60s bigint not null, reducao double precision not null,
    pares bigint not null, pulo_primeiro bigint not null, pulo_colado bigint not null,
    var_n double precision"""

# nome: (colunas da tabela, chave primaria, como trocar). "janela" apaga so os
# dias exportados; "tudo" esvazia a tabela.
TABELAS = {
    "linha_dia_faixa": (
        "route_id text not null, direction_id smallint not null, data_bh date not null,"
        " faixa_horaria text not null, ordem_faixa smallint not null, tipo_dia text not null,"
        " alta_frequencia boolean not null," + SOMAS_DDL,
        "route_id, direction_id, data_bh, faixa_horaria", "janela"),
    "hist_dia": (
        "data_bh date not null, tipo_dia text not null, alta_frequencia boolean not null,"
        " classe smallint not null, headways bigint not null",
        "data_bh, tipo_dia, alta_frequencia, classe", "janela"),
    "paradas_28d": (
        "stop_id text not null, tipo_dia text not null, alta_frequencia boolean not null," + SOMAS_DDL + ","
        " linhas bigint not null, stop_name text, stop_lat double precision, stop_lon double precision,"
        " janela_ini date not null, janela_fim date not null",
        "stop_id, tipo_dia, alta_frequencia", "tudo"),
    "qualidade_diaria": (
        "data_bh date not null, passagens bigint, passagens_validas bigint,"
        " descartadas_intervalo_longo bigint, descartadas_sem_mapa bigint, paradas_pelo_mapa bigint,"
        " instantes_divididos bigint, headways bigint, headways_validos bigint, headways_longos bigint,"
        " headways_feed_parado bigint, linhas bigint, cobertura_passagens double precision",
        "data_bh", "janela"),
    "ml_resumo": (
        "data_bh date not null, conjunto text not null, route_id text not null,"
        " versao_modelo text not null, limiar double precision not null, exemplos bigint not null,"
        " positivos bigint not null, alertas bigint not null, acertos bigint not null",
        "data_bh, conjunto, route_id, versao_modelo", "tudo"),
    "linhas": ("route_id text not null, route_long_name text", "route_id", "tudo"),
}


def janela(ate: date, dias: int, tudo: bool) -> tuple[date, date, date]:
    """(de, ate, inicio das paradas). Nunca antes do primeiro dia cheio."""
    de = DATA_INICIO if tudo else max(DATA_INICIO, ate - timedelta(days=dias - 1))
    return de, ate, max(DATA_INICIO, ate - timedelta(days=DIAS_PARADAS - 1))


def colunas(tabela: str) -> list[str]:
    return [c.strip().split()[0] for c in TABELAS[tabela][0].split(",")]


def ddl(tabela: str) -> str:
    cols, chave, _ = TABELAS[tabela]
    return f"create table if not exists {ESQUEMA}.{tabela} ({cols}, primary key ({chave}))"


def apagar(tabela: str) -> str:
    if TABELAS[tabela][2] == "janela":
        return f"delete from {ESQUEMA}.{tabela} where data_bh between %s and %s"
    return f"delete from {ESQUEMA}.{tabela}"


def montar(spark, de: date, ate: date, ini_paradas: date) -> dict[str, list[tuple]]:
    """Linhas de cada tabela, ja na ordem das colunas."""
    from pyspark.sql import functions as F

    from servico.metricas import SOMAS, calcular_grupos, preparar, somar

    def ler(caminho):
        return spark.read.format("delta").load(f"{G}/{caminho}")

    def gtfs(nome):
        return spark.read.csv(f"{GTFS}/{nome}.txt", header=True, inferSchema=False)

    def linhas(df, tabela):
        return [tuple(r) for r in df.select(*colunas(tabela)).collect()]

    grupos, hist = calcular_grupos(ler, min(de, ini_paradas), ate)
    gr = preparar(grupos).cache()
    no_periodo = f"data_bh between '{de}' and '{ate}'"

    lin = somar(gr.where(no_periodo), ["route_id", "direction_id", "data_bh", "faixa_horaria",
                                       "ordem_faixa", "tipo_dia", "alta_frequencia"])
    hd = (hist.where(no_periodo).groupBy("data_bh", "tipo_dia", "alta_frequencia", "classe")
              .agg(F.sum("count").alias("headways")))

    tipo = ["tipo_dia", "alta_frequencia"]
    p = gr.where(f"data_bh between '{ini_paradas}' and '{ate}'")
    pontos = gtfs("stops").select(
        "stop_id", "stop_name", F.col("stop_lat").cast("double"), F.col("stop_lon").cast("double"))
    par = (somar(p, tipo + ["stop_id"])
           .join(p.groupBy(*tipo, "stop_id").agg(F.countDistinct("route_id").alias("linhas")), tipo + ["stop_id"])
           .join(pontos, "stop_id", "left")
           .withColumn("janela_ini", F.lit(ini_paradas)).withColumn("janela_fim", F.lit(ate)))

    q = ler("marts/fct_qualidade_diaria").where(no_periodo)

    ml = (ler("ml/previsao_bunching")
          .groupBy("data_bh", "conjunto", "route_id", "versao_modelo")
          .agg(F.max("limiar").alias("limiar"), F.count("*").alias("exemplos"),
               F.sum(F.col("alvo").cast("bigint")).alias("positivos"),
               F.sum(F.col("alerta").cast("bigint")).alias("alertas"),
               F.sum((F.col("alerta") & (F.col("alvo") == 1)).cast("bigint")).alias("acertos")))

    # O route_id do feed em tempo real e o route_short_name do GTFS (analise/calcular.py).
    rotas = (gtfs("routes").select(F.col("route_short_name").alias("route_id"), "route_long_name")
             .dropDuplicates(["route_id"]))

    assert SOMAS == colunas("linha_dia_faixa")[7:], "SOMAS fora de ordem com a tabela"
    return {
        "linha_dia_faixa": linhas(lin, "linha_dia_faixa"),
        "hist_dia": linhas(hd, "hist_dia"),
        "paradas_28d": linhas(par, "paradas_28d"),
        "qualidade_diaria": linhas(q, "qualidade_diaria"),
        "ml_resumo": linhas(ml, "ml_resumo"),
        "linhas": linhas(rotas, "linhas"),
    }


def gravar(url: str, dados: dict[str, list[tuple]], de: date, ate: date) -> dict[str, int]:
    """Troca tudo numa transacao e confere as contagens antes de confirmar."""
    import psycopg

    with psycopg.connect(url, connect_timeout=60) as con:  # o Neon pode estar acordando
        with con.transaction(), con.cursor() as cur:
            cur.execute(f"create schema if not exists {ESQUEMA}")
            for t in TABELAS:
                cur.execute(ddl(t))
            cur.execute(f"""create table if not exists {ESQUEMA}.cargas (
                carregado_em timestamptz not null default now(), de date not null,
                ate date not null, linhas jsonb not null)""")
            for t, linhas in dados.items():
                cur.execute(apagar(t), (de, ate) if TABELAS[t][2] == "janela" else None)
                cols = colunas(t)
                with cur.copy(f"copy {ESQUEMA}.{t} ({', '.join(cols)}) from stdin") as cp:
                    for r in linhas:
                        cp.write_row(r)
            contagem = {}
            for t, linhas in dados.items():
                if TABELAS[t][2] == "janela":
                    cur.execute(f"select count(*) from {ESQUEMA}.{t} where data_bh between %s and %s", (de, ate))
                else:
                    cur.execute(f"select count(*) from {ESQUEMA}.{t}")
                contagem[t] = cur.fetchone()[0]
                if contagem[t] != len(linhas):
                    raise RuntimeError(f"{t}: {contagem[t]} no banco, {len(linhas)} enviadas")
            cur.execute(f"insert into {ESQUEMA}.cargas (de, ate, linhas) values (%s, %s, %s)",
                        (de, ate, json.dumps(contagem)))
        with con.cursor() as cur:
            cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
            contagem["tamanho_banco"] = cur.fetchone()[0]
    return contagem


def url_do_banco(env_arquivo: str = "/app/.env") -> str:
    """NEON_URL do ambiente ou, na falta, do .env do projeto montado em /app.

    Ler o arquivo no conteiner evita passar a senha pelo Airflow, que guardaria
    os argumentos da tarefa no banco dele.
    """
    url = os.environ.get("NEON_URL", "").strip()
    if not url and os.path.exists(env_arquivo):
        with open(env_arquivo, encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("NEON_URL="):
                    url = linha.split("=", 1)[1].strip().strip("'\"")
    return url


def ontem_bh() -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ate", type=date.fromisoformat, default=None, help="ultimo dia de BH (padrao: ontem)")
    ap.add_argument("--dias", type=int, default=3, help="dias recalculados ate --ate")
    ap.add_argument("--tudo", action="store_true", help=f"recalcula desde {DATA_INICIO}")
    ap.add_argument("--seco", action="store_true", help="monta e conta, sem gravar no banco")
    a = ap.parse_args(argv)
    de, ate, ini_paradas = janela(a.ate or ontem_bh(), a.dias, a.tudo)
    if ate < DATA_INICIO:
        sys.exit(f"--ate {ate} antes do primeiro dia da Gold ({DATA_INICIO})")
    url = url_do_banco()
    if not url and not a.seco:
        sys.exit("NEON_URL nao definida (fica no ~/radar/.env da VM de processamento)")

    sys.path.insert(0, "/app")
    from silver.processar import sessao
    spark = sessao("3g")
    spark.sparkContext.setLogLevel("ERROR")
    print(f"janela {de} a {ate}, paradas desde {ini_paradas}", flush=True)
    dados = montar(spark, de, ate, ini_paradas)
    print({t: len(v) for t, v in dados.items()}, flush=True)
    if not a.seco:
        print(gravar(url, dados, de, ate), flush=True)


if __name__ == "__main__":
    main()
