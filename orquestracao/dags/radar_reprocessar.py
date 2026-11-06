"""DAG de reprocessamento: refaz uma janela de datas de BH, sob demanda.

Para depois de uma correcao: "refaz a Silver de 19 a 25/10 e a Gold que depende
dela" vira um clique, com de e ate. Idempotente como a DAG horaria: rodar duas
vezes a mesma janela da as mesmas tabelas.

- camadas = silver_e_gold: traz os conteineres do bucket, refaz a Silver e a Gold
  de `de` ate o dia seguinte a `ate` (as viagens da madrugada seguinte comecam em
  `ate`).
- camadas = so_gold: para uma correcao so no dbt. A Silver nao e tocada.

Para reconstruir a Gold inteira, de = 2026-09-15 e ate = hoje.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from airflow.providers.standard.operators.python import ShortCircuitOperator
from airflow.sdk import DAG, Param

from radar_comum import DATA_MINIMA, janela_gold_do_reprocessamento
from radar_tarefas import IMAGEM_GOLD, POOL_SPARK, no_conteiner


def precisa_silver(params, **_) -> bool:
    janela_gold_do_reprocessamento(params["de"], params["ate"])  # valida as datas antes de gastar Spark
    return params["camadas"] == "silver_e_gold"


with DAG(
    dag_id="radar_reprocessar",
    description="Refaz Silver e Gold de uma janela de datas de BH",
    schedule=None,
    start_date=datetime(2026, 9, 15, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    params={
        "de": Param(str(DATA_MINIMA), type="string", format="date", description="primeiro dia de BH"),
        "ate": Param(str(date.today()), type="string", format="date", description="ultimo dia de BH"),
        "camadas": Param("silver_e_gold", enum=["silver_e_gold", "so_gold"]),
    },
    user_defined_macros={"janela_gold": janela_gold_do_reprocessamento},
    default_args={"retries": 0},
    tags=["radar"],
) as dag:
    checar = ShortCircuitOperator(
        task_id="precisa_silver",
        python_callable=precisa_silver,
        # Pula so a Silver; a Gold roda nos dois casos.
        ignore_downstream_trigger_rules=False,
    )

    sincronizar = no_conteiner(
        "sincronizar", "python -m silver.sincronizar --de {{ params.de }} --ate {{ params.ate }}",
    )

    silver = no_conteiner(
        "silver", "python -m silver.processar --de {{ params.de }} --ate {{ params.ate }}", pool=POOL_SPARK,
    )

    gold = no_conteiner(
        "gold",
        "dbt build --vars '{{ janela_gold(params.de, params.ate) }}'",
        imagem=IMAGEM_GOLD,
        pasta="/app/gold",
        pool=POOL_SPARK,
        trigger_rule="none_failed",
    )

    # Sem aresta direta checar -> gold: o ShortCircuit pularia a Gold junto. Com a
    # Silver pulada, none_failed deixa a Gold rodar; com erro, nao.
    checar >> sincronizar >> silver >> gold
