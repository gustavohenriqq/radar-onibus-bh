"""Regras da limpeza do Airflow, sem importar o Airflow.

O Airflow nao apaga nada sozinho: cada execucao deixa log por tarefa em
orquestracao/logs e linhas no Postgres dele. A DAG radar_limpeza apaga o que
passou de RETENCAO_DIAS.

Os logs do reprocessamento por janela ficam para sempre: roda a mao, poucas
vezes, e o log dele e a prova do que foi refeito e quando. No banco ele vence
como o resto (ver comando_db_clean).

So entra aqui o que e do Airflow. Bronze, Silver e Gold nao sao tocados.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

RETENCAO_DIAS = 30
DAGS_PRESERVADAS = ("radar_reprocessar",)


def limite(agora: datetime, dias: int = RETENCAO_DIAS) -> datetime:
    """Tudo que for anterior a este instante (UTC) vence."""
    return agora.astimezone(timezone.utc) - timedelta(days=dias)


def comando_db_clean(antes_de: datetime, seco: bool = False) -> list[str]:
    """`airflow db clean` sem tabela de arquivo: arquivar so mudaria o lixo de
    lugar. A regra do proprio Airflow mantem a ultima execucao agendada de cada
    DAG, entao o agendamento nao recua.

    Sem --exclude-dag-ids: no Airflow 3.3.2 a configuracao do comando diz que
    deadline, asset_event e task_reschedule tem dag_id, mas as tabelas reais nao
    tem, e o filtro falha nelas ("column base.dag_id does not exist", visto em
    07/11/2026). Pior: limpar dag_run puxa deadline junto, entao nao da para
    contornar separando as tabelas. O reprocessamento fica preservado nos
    arquivos de log, que e onde esta a saida de cada etapa."""
    cmd = [
        "airflow", "db", "clean",
        "--clean-before-timestamp", antes_de.astimezone(timezone.utc).isoformat(),
        "--skip-archive",
        "--error-on-cleanup-failure",
        "--yes",
    ]
    if seco:
        cmd.append("--dry-run")
    return cmd


def _preservada(raiz: Path, pasta: str) -> bool:
    rel = Path(pasta).relative_to(raiz).parts
    return bool(rel) and rel[0] in {f"dag_id={d}" for d in DAGS_PRESERVADAS}


def logs_vencidos(raiz: Path, antes_de: datetime) -> list[Path]:
    """Arquivos de log modificados antes de `antes_de`, fora das DAGs preservadas.
    Links simbolicos (o `latest` do processador de DAGs) nao sao seguidos nem
    apagados."""
    corte = antes_de.timestamp()
    vencidos = []
    for pasta, subpastas, arquivos in os.walk(raiz):
        if _preservada(raiz, pasta):
            subpastas.clear()
            continue
        for nome in arquivos:
            p = Path(pasta) / nome
            if not p.is_symlink() and p.stat().st_mtime < corte:
                vencidos.append(p)
    return sorted(vencidos)


def apagar_logs(raiz: Path, antes_de: datetime, seco: bool = False) -> tuple[int, int]:
    """Apaga os logs vencidos e as pastas que ficaram vazias. Devolve (arquivos,
    bytes). Pasta vazia mas recente fica: o Airflow cria a pasta da tarefa um
    instante antes de gravar o log."""
    raiz = Path(raiz)
    vencidos = logs_vencidos(raiz, antes_de)
    tamanho = sum(p.stat().st_size for p in vencidos)
    if seco:
        return len(vencidos), tamanho
    # Apagar um arquivo atualiza a data da pasta: as que esta limpeza esvaziou
    # valem como velhas mesmo assim.
    esvaziadas = set()
    for p in vencidos:
        p.unlink()
        esvaziadas.add(p.parent)
    corte = antes_de.timestamp()
    for pasta, _, _ in os.walk(raiz, topdown=False):
        p = Path(pasta)
        if p == raiz or p.is_symlink() or _preservada(raiz, pasta):
            continue
        if not any(p.iterdir()) and (p in esvaziadas or p.stat().st_mtime < corte):
            p.rmdir()
            esvaziadas.add(p.parent)
    return len(vencidos), tamanho
