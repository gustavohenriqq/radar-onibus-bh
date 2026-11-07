"""DAG diaria de limpeza do proprio Airflow: banco e logs com mais de 30 dias.

Sem ela, as 24 execucoes por dia da DAG horaria acumulam log por tarefa e linhas
no Postgres sem limite. As regras (o que vence, o que fica) estao em
radar_limpeza_regras.py e tem teste no pytest do projeto.

Roda as 06:30 UTC, dentro do scheduler, e as duas tarefas pegam o pool `spark`:
nunca disputam a VM com a Silver ou a Gold, e esperam o Spark da hora acabar.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from radar_limpeza_regras import apagar_logs, comando_db_clean, limite
from radar_tarefas import POOL_SPARK, avisar_falha

log = logging.getLogger(__name__)
PASTA_LOGS = "/opt/airflow/logs"


def _env_com_banco() -> dict:
    """O Airflow 3 tira o banco de metadados do processo da tarefa: troca a URL
    por uma invalida. O `db clean` e comando de administrador e precisa dela, entao
    a URL e remontada so para ele, com a mesma senha do .env que o
    docker-compose.yml usa. Nada disso vai para o log."""
    env = dict(os.environ)
    senha = quote(os.environ["POSTGRES_SENHA"], safe="")
    env["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = f"postgresql+psycopg2://airflow:{senha}@postgres/airflow"
    env.pop("AIRFLOW__CORE__SQL_ALCHEMY_CONN", None)
    return env


def limpar_banco(**_) -> None:
    cmd = comando_db_clean(limite(datetime.now(timezone.utc)))
    log.info("%s", " ".join(cmd))
    subprocess.run(cmd, check=True, env=_env_com_banco())


def limpar_logs(**_) -> None:
    antes_de = limite(datetime.now(timezone.utc))
    n, tamanho = apagar_logs(PASTA_LOGS, antes_de)
    log.info("logs anteriores a %s: %d arquivos, %.1f MB apagados", antes_de, n, tamanho / 1e6)


with DAG(
    dag_id="radar_limpeza",
    description="Apaga banco e logs do Airflow com mais de 30 dias",
    schedule="30 6 * * *",
    start_date=datetime(2026, 11, 7, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=30),
        "pool": POOL_SPARK,
        "on_failure_callback": avisar_falha,
    },
    tags=["radar"],
) as dag:
    banco = PythonOperator(task_id="limpar_banco", python_callable=limpar_banco)
    logs = PythonOperator(task_id="limpar_logs", python_callable=limpar_logs)

    banco >> logs
