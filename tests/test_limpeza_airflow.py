"""Limpeza do Airflow: o que vence, o que fica e o comando do banco.

A regra mora em orquestracao/dags/radar_limpeza_regras.py, sem o Airflow, para
rodar no pytest local. A DAG em si e conferida no proprio Airflow, na VM.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from orquestracao.dags.radar_limpeza_regras import (
    apagar_logs,
    comando_db_clean,
    limite,
    logs_vencidos,
)

UTC = timezone.utc
AGORA = datetime(2026, 12, 10, 6, 30, tzinfo=UTC)
CORTE = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 30 dias antes


def _arquivo(raiz, rel, quando):
    p = raiz / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x" * 10)
    t = quando.timestamp()
    os.utime(p, (t, t))
    return p


def _envelhecer_pastas(raiz, quando):
    t = quando.timestamp()
    for pasta, _, _ in os.walk(raiz):
        if pasta != str(raiz):
            os.utime(pasta, (t, t))


def test_limite_e_trinta_dias_antes_em_utc():
    assert limite(AGORA) == CORTE
    from zoneinfo import ZoneInfo

    assert limite(AGORA.astimezone(ZoneInfo("America/Sao_Paulo"))) == CORTE


def test_so_vence_log_mais_velho_que_o_corte(tmp_path):
    velho = _arquivo(tmp_path, "dag_id=radar_horario/run_id=a/task_id=silver/attempt=1.log", datetime(2026, 11, 1, tzinfo=UTC))
    _arquivo(tmp_path, "dag_id=radar_horario/run_id=b/task_id=silver/attempt=1.log", datetime(2026, 11, 20, tzinfo=UTC))
    assert logs_vencidos(tmp_path, CORTE) == [velho]


def test_reprocessamento_nunca_vence(tmp_path):
    _arquivo(tmp_path, "dag_id=radar_reprocessar/run_id=prova_1/task_id=gold/attempt=1.log", datetime(2026, 1, 1, tzinfo=UTC))
    assert logs_vencidos(tmp_path, CORTE) == []


def test_link_simbolico_fica(tmp_path):
    alvo = _arquivo(tmp_path, "dag_processor/2026-12-10/radar_horario.py.log", AGORA)
    link = tmp_path / "dag_processor" / "latest"
    try:
        link.symlink_to(alvo.parent, target_is_directory=True)
    except OSError:
        pytest.skip("sem permissao para criar link simbolico")
    t = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    os.utime(link, (t, t), follow_symlinks=False)
    assert logs_vencidos(tmp_path, CORTE) == []


def test_apagar_remove_arquivos_e_pastas_vazias_velhas(tmp_path):
    velho = datetime(2026, 11, 1, tzinfo=UTC)
    _arquivo(tmp_path, "dag_id=radar_horario/run_id=a/task_id=silver/attempt=1.log", velho)
    _arquivo(tmp_path, "dag_id=radar_horario/run_id=a/task_id=gold/attempt=1.log", velho)
    novo = _arquivo(tmp_path, "dag_id=radar_horario/run_id=b/task_id=silver/attempt=1.log", AGORA)
    _envelhecer_pastas(tmp_path, velho)

    n, tamanho = apagar_logs(tmp_path, CORTE)

    assert (n, tamanho) == (2, 20)
    assert not (tmp_path / "dag_id=radar_horario" / "run_id=a").exists()
    assert novo.exists()
    assert tmp_path.exists()


def test_pasta_vazia_recente_fica(tmp_path):
    """Pasta recem-criada e ainda sem arquivo: o Airflow vai gravar nela."""
    (tmp_path / "dag_id=radar_horario" / "run_id=c" / "task_id=silver").mkdir(parents=True)
    apagar_logs(tmp_path, limite(datetime.now(UTC)))
    assert (tmp_path / "dag_id=radar_horario" / "run_id=c" / "task_id=silver").exists()


def test_seco_so_conta(tmp_path):
    velho = _arquivo(tmp_path, "dag_id=radar_horario/run_id=a/task_id=silver/attempt=1.log", datetime(2026, 11, 1, tzinfo=UTC))
    assert apagar_logs(tmp_path, CORTE, seco=True) == (1, 10)
    assert velho.exists()


def test_banco_nao_arquiva_e_falha_alto():
    cmd = comando_db_clean(CORTE)
    assert cmd[:3] == ["airflow", "db", "clean"]
    assert cmd[cmd.index("--clean-before-timestamp") + 1] == "2026-11-10T06:30:00+00:00"
    for opcao in ("--skip-archive", "--yes", "--error-on-cleanup-failure"):
        assert opcao in cmd
    assert "--dry-run" not in cmd
    assert "--dry-run" in comando_db_clean(CORTE, seco=True)


def test_banco_sem_filtro_por_dag():
    """Bug do Airflow 3.3.2: o filtro por DAG quebra em deadline, que dag_run
    puxa junto."""
    assert "--exclude-dag-ids" not in comando_db_clean(CORTE)
    assert "--dag-ids" not in comando_db_clean(CORTE)
