"""DAG horaria: hora fechada no bucket -> Silver -> Gold.

Para cada hora UTC H, a execucao comeca em H+1 e espera o manifesto de H chegar ao
bucket (o backup envia a hora fechada ha 2 h, no minuto 45). Depois:

1. traz o conteiner de H para o disco da VM, conferido por SHA-256;
2. MERGE de H na Silver;
3. Gold de ontem e hoje (dias de BH), regravando so essas particoes;
4. na ultima hora do dia de BH, OPTIMIZE da Silver daquele dia;
5. na ultima hora do domingo, VACUUM da Silver e da Gold.

Tudo e idempotente: rodar a mesma hora de novo nao muda nenhuma tabela. O coletor
fica fora do Airflow, como o README decidiu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airflow.providers.standard.operators.python import PythonOperator, ShortCircuitOperator
from airflow.providers.standard.sensors.python import PythonSensor
from airflow.sdk import DAG
from airflow.timetables.interval import CronDataIntervalTimetable

from radar_comum import data_bh, fecha_dia_bh, fecha_semana_bh, hora_texto, janela_gold_da_hora
from radar_tarefas import IMAGEM_GOLD, POOL_SPARK, avisar_falha, manifesto_no_bucket, no_conteiner, pingar

with DAG(
    dag_id="radar_horario",
    description="Silver e Gold por hora fechada",
    schedule=CronDataIntervalTimetable("0 * * * *", timezone="UTC"),
    # 05/11/2026 00:00 em BH: o backfill a mao cobriu ate 04/11.
    start_date=datetime(2026, 11, 5, 3, tzinfo=timezone.utc),
    catchup=True,
    max_active_runs=1,
    user_defined_macros={"hora_texto": hora_texto, "janela_gold": janela_gold_da_hora, "data_bh": data_bh},
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "on_failure_callback": avisar_falha,
    },
    tags=["radar"],
) as dag:
    aguardar = PythonSensor(
        task_id="aguardar_backup",
        python_callable=manifesto_no_bucket,
        mode="reschedule",
        poke_interval=5 * 60,
        # 6 h: cobre o atraso normal (cerca de 2 h 45) e uma noite ruim do backup.
        # Hora que nunca vai existir (coletor parado a hora inteira) falha aqui.
        timeout=6 * 3600,
        retries=0,
    )

    sincronizar = no_conteiner(
        "sincronizar",
        "python -m silver.sincronizar --hora {{ hora_texto(data_interval_start) }}",
    )

    silver = no_conteiner(
        "silver",
        "python -m silver.processar --hora {{ hora_texto(data_interval_start) }} --sem-optimize",
        pool=POOL_SPARK,
    )

    gold = no_conteiner(
        "gold",
        "dbt build --vars '{{ janela_gold(data_interval_start) }}'",
        imagem=IMAGEM_GOLD,
        pasta="/app/gold",
        pool=POOL_SPARK,
    )

    avisar = PythonOperator(task_id="avisar_ok", python_callable=pingar)

    fim_do_dia = ShortCircuitOperator(
        task_id="fim_do_dia_bh",
        python_callable=lambda data_interval_start, **_: fecha_dia_bh(data_interval_start),
    )

    optimize = no_conteiner(
        "optimize_silver",
        "python -m silver.manutencao optimize"
        " --de {{ data_bh(data_interval_start) }} --ate {{ data_bh(data_interval_start) }}",
        pool=POOL_SPARK,
    )

    fim_da_semana = ShortCircuitOperator(
        task_id="fim_da_semana_bh",
        python_callable=lambda data_interval_start, **_: fecha_semana_bh(data_interval_start),
    )

    vacuum_silver = no_conteiner("vacuum_silver", "python -m silver.manutencao vacuum", pool=POOL_SPARK)

    vacuum_gold = no_conteiner(
        "vacuum_gold", "dbt run-operation vacuum_gold", imagem=IMAGEM_GOLD, pasta="/app/gold", pool=POOL_SPARK,
    )

    aguardar >> sincronizar >> silver >> gold >> [avisar, fim_do_dia]
    fim_do_dia >> optimize >> fim_da_semana >> vacuum_silver >> vacuum_gold
