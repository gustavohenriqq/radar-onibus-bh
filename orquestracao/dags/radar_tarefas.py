"""Pecas comuns das DAGs: tarefa em conteiner, espera pelo backup e aviso.

Cada etapa roda numa das imagens que ja rodavam a mao (radar-spark e radar-gold),
pelo socket do Docker da VM. O Airflow so decide quando e em que ordem: nenhuma
regra de negocio mora aqui.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

import requests
from docker.types import Mount

from airflow.providers.docker.operators.docker import DockerOperator

from radar_comum import nome_manifesto

log = logging.getLogger(__name__)

# Caminhos do host: o conteiner da tarefa e irmao do Airflow, nao filho.
RADAR_DIR = os.environ.get("RADAR_DIR", "/home/ubuntu/radar")
IVY_DIR = os.environ.get("RADAR_IVY_DIR", "/home/ubuntu/ivy")
IMAGEM_SPARK = os.environ.get("RADAR_IMAGEM_SPARK", "radar-spark:dev")
IMAGEM_GOLD = os.environ.get("RADAR_IMAGEM_GOLD", "radar-gold:dev")

# Um Spark por vez: a VM tem 12 GB, e a Gold sozinha pede 8 GB de driver.
POOL_SPARK = "spark"


def no_conteiner(task_id: str, comando: str, imagem: str = IMAGEM_SPARK, pasta: str = "/app", **kw):
    return DockerOperator(
        task_id=task_id,
        image=imagem,
        command=comando,
        working_dir=pasta,
        mounts=[
            Mount(target="/app", source=RADAR_DIR, type="bind"),
            # Spark 4 guarda os jars do Delta aqui: sem o volume, baixaria a cada tarefa.
            Mount(target="/root/.ivy2.5.2", source=IVY_DIR, type="bind"),
        ],
        docker_url="unix://var/run/docker.sock",
        auto_remove="success",
        mount_tmp_dir=False,
        **kw,
    )


def manifesto_no_bucket(data_interval_start, **_) -> bool:
    """HEAD no manifesto da hora. 200: a hora inteira ja esta no bucket."""
    url = os.environ["BACKUP_PAR_URL"]
    nome = nome_manifesto(data_interval_start)
    r = requests.head(url + quote(nome, safe="/"), timeout=30)
    if r.status_code not in (200, 404):
        r.raise_for_status()
    log.info("%s: http %s", nome, r.status_code)
    return r.status_code == 200


def pingar(sufixo: str = "") -> None:
    """Healthchecks: sem ping no prazo, ou com /fail, o dono e avisado."""
    url = os.environ.get("HEALTHCHECK_PROCESSAMENTO_URL", "").strip()
    if not url:
        log.warning("HEALTHCHECK_PROCESSAMENTO_URL vazia: sem aviso externo")
        return
    try:
        requests.post(url + sufixo, timeout=15)
    except requests.RequestException as e:
        # O aviso nao pode derrubar a tarefa: o healthchecks reclama sozinho se o
        # ping nao chegar.
        log.warning("ping falhou: %s", e)


def avisar_falha(context) -> None:
    ti = context["ti"]
    log.error("falha em %s.%s", ti.dag_id, ti.task_id)
    pingar("/fail")
