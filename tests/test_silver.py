"""Testes da Silver.

Os de decodificacao e janela rodam em qualquer lugar. Os de Spark rodam no
contêiner (Dockerfile.spark) e sao pulados onde nao ha pyspark. O de taxa de
duplicacao usa dado real: aponte RADAR_DADOS_REAIS para uma pasta com
bronze_horario/ do dia 15/09/2026 (por exemplo, restaurada com
`python -m backup.restaurar --dia 2026-09-15`).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

gtfs = pytest.importorskip("google.transit.gtfs_realtime_pb2")

from compactacao import formato
from compactacao.horas import Hora
from silver.decodificar import COLUNAS, decodificar, taxa_de_duplicacao
from silver.janela import hora_utc, horas_utc_do_dia

UTC = timezone.utc


def feed(ts_coleta: datetime, veiculos: list[dict]) -> bytes:
    f = gtfs.FeedMessage()
    f.header.gtfs_realtime_version = "1.0"
    f.header.timestamp = int(ts_coleta.timestamp())
    for i, v in enumerate(veiculos):
        e = f.entity.add()
        e.id = str(i)
        e.vehicle.vehicle.id = v["id"]
        e.vehicle.timestamp = int(v["ts"].timestamp())
        e.vehicle.trip.route_id = v.get("linha", "30")
        e.vehicle.trip.trip_id = v.get("viagem", "t1")
        e.vehicle.position.latitude = v.get("lat", -19.9)
        e.vehicle.position.longitude = v.get("lon", -43.9)
        if "vel" in v:
            e.vehicle.position.speed = v["vel"]
    return f.SerializeToString()


def nome(ts: datetime) -> str:
    return ts.strftime("%Y%m%dT%H%M%SZ")


# --- janela e decodificacao (sem Spark) -------------------------------------

def test_dia_de_bh_comeca_as_3h_utc():
    horas = horas_utc_do_dia(date(2026, 9, 15))
    assert len(horas) == 24
    assert (horas[0].dt, horas[0].hh) == ("2026-09-15", "03")
    assert (horas[-1].dt, horas[-1].hh) == ("2026-09-16", "02")


def test_hora_do_airflow_vira_hora_utc_do_bronze():
    # O Airflow entrega o inicio do intervalo em ISO, com fuso; so a hora importa.
    assert hora_utc("2026-11-05T14:00:00+00:00") == Hora("2026-11-05", "14")
    assert hora_utc("2026-11-05T03") == Hora("2026-11-05", "03")


def test_campo_ausente_vira_none_e_nao_zero():
    t = datetime(2026, 9, 15, 10, tzinfo=UTC)
    sem_vel, com_vel = decodificar(nome(t), feed(t, [{"id": "a", "ts": t}, {"id": "b", "ts": t, "vel": 0.0}]))
    i = COLUNAS.index("speed")
    # ausente e "nao informado"; zero e "parado"
    assert sem_vel[i] is None
    assert com_vel[i] == 0.0
    assert sem_vel[COLUNAS.index("coleta_ts")] == t


def test_taxa_de_duplicacao_conta_pela_chave_do_feed():
    t = datetime(2026, 9, 15, 10, tzinfo=UTC)
    c1 = list(decodificar(nome(t), feed(t, [{"id": "a", "ts": t}, {"id": "b", "ts": t}])))
    # 30 s depois: "a" nao atualizou a posicao, "b" atualizou
    t2 = t + timedelta(seconds=30)
    c2 = list(decodificar(nome(t2), feed(t2, [{"id": "a", "ts": t}, {"id": "b", "ts": t2}])))
    assert taxa_de_duplicacao(c1 + c2) == (4, 3, 0.25)


# --- dado real: reproduz a auditoria de 16/09/2026 ---------------------------

REAIS = os.environ.get("RADAR_DADOS_REAIS")


@pytest.mark.skipif(not REAIS, reason="RADAR_DADOS_REAIS nao definida")
@pytest.mark.parametrize("hh, registros, unicos, pct", [
    ("10", 120_590, 72_290, 40.1),   # pico da manha, 07h em BH
    ("05", 2_633, 2_172, 17.5),      # madrugada, 02h em BH
])
def test_taxa_de_duplicacao_bate_com_a_auditoria(hh, registros, unicos, pct):
    # A auditoria leu as 60 primeiras coletas da hora (30 min)
    conteiner = Hora("2026-09-15", hh).conteiner(Path(REAIS) / "bronze_horario" / "vehicle_positions")
    linhas = []
    for i, (n, pb) in enumerate(formato.ler(conteiner)):
        if i == 60:
            break
        linhas.extend(decodificar(n, pb))
    total, distintos, taxa = taxa_de_duplicacao(linhas)
    assert (total, distintos) == (registros, unicos)
    assert round(100 * taxa, 1) == pct


# --- Spark + Delta (no contêiner) -------------------------------------------

@pytest.fixture(scope="module")
def spark():
    pytest.importorskip("pyspark")
    pytest.importorskip("delta")
    from silver.processar import sessao
    s = sessao(memoria="1g")
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


def semear_bronze(dados: Path, coletas: dict[datetime, list[dict]]) -> None:
    """Grava contêineres horarios a partir de feeds sinteticos, pelo formato real."""
    from coletor.armazenamento import caminho_arquivo, gravar_atomico
    from compactacao.compactar import compactar_hora
    from coletor.config import Config
    cfg = Config(url="", dir_dados=dados, dir_log=dados / "logs", intervalo_s=30, timeout_s=15,
                 backoff_max_s=300, alerta_sem_arquivo_min=10, user_agent="t", healthcheck_url=None, healthcheck_compactacao_url=None,
                 compactacao_folga_min=20, compactacao_quarentena_h=48, compactacao_nivel_zstd=3)
    horas = set()
    for ts, veiculos in coletas.items():
        gravar_atomico(caminho_arquivo(cfg.dir_bronze, ts), feed(ts, veiculos))
        horas.add(Hora(ts.strftime("%Y-%m-%d"), ts.strftime("%H")))
    for h in horas:
        compactar_hora(h, cfg)


def utc(ts: datetime) -> datetime:
    # O Spark devolve timestamp sem fuso, ja no fuso da sessao (UTC)
    return ts.replace(tzinfo=None)


def tabela(spark, destino):
    return sorted(tuple(r) for r in spark.read.format("delta").load(destino)
                  .select("vehicle_id", "vehicle_ts", "primeira_coleta_ts", "data_bh", "route_id").collect())


def test_merge_deduplica_e_reprocessar_nao_muda_nada(spark, tmp_path):
    from silver.processar import processar_dia
    t = datetime(2026, 9, 15, 10, tzinfo=UTC)  # 07h em BH, dia 15
    semear_bronze(tmp_path, {
        t: [{"id": "a", "ts": t}, {"id": "b", "ts": t}],
        t + timedelta(seconds=30): [{"id": "a", "ts": t}, {"id": "b", "ts": t + timedelta(seconds=25)}],
        t + timedelta(seconds=60): [{"id": "a", "ts": t}, {"id": "b", "ts": t + timedelta(seconds=25)}],
    })
    destino = str(tmp_path / "silver")
    dir_h = tmp_path / "bronze_horario" / "vehicle_positions"

    r1 = processar_dia(spark, date(2026, 9, 15), dir_h, destino)
    assert (r1["registros"], r1["unicos"], r1["inseridas"]) == (6, 3, 3)
    antes = tabela(spark, destino)
    # "a" ficou com a primeira coleta que o viu
    assert [x for x in antes if x[0] == "a"][0][2] == utc(t)

    r2 = processar_dia(spark, date(2026, 9, 15), dir_h, destino)
    assert (r2["inseridas"], r2["atualizadas"]) == (0, 0)
    assert tabela(spark, destino) == antes


def test_posicao_vista_em_duas_janelas_fica_com_a_primeira_coleta(spark, tmp_path):
    from silver.processar import processar_dia
    # 02:59:30 UTC e o fim do dia 14 em BH; 03:00:00 UTC ja e o dia 15.
    fim_14 = datetime(2026, 9, 15, 2, 59, 30, tzinfo=UTC)
    inicio_15 = datetime(2026, 9, 15, 3, 0, 0, tzinfo=UTC)
    pos = datetime(2026, 9, 15, 2, 59, 20, tzinfo=UTC)  # 23:59:20 em BH, dia 14
    semear_bronze(tmp_path, {fim_14: [{"id": "a", "ts": pos}], inicio_15: [{"id": "a", "ts": pos}]})
    destino = str(tmp_path / "silver")
    dir_h = tmp_path / "bronze_horario" / "vehicle_positions"

    # ordem "errada" de proposito: o dia 15 primeiro
    processar_dia(spark, date(2026, 9, 15), dir_h, destino)
    processar_dia(spark, date(2026, 9, 14), dir_h, destino)
    linhas = tabela(spark, destino)
    assert len(linhas) == 1
    _, _, primeira, data_bh, _ = linhas[0]
    assert primeira == utc(fim_14)
    # particao pela data do evento em BH, nao pela data da coleta
    assert data_bh == date(2026, 9, 14)


@pytest.mark.skipif(not REAIS, reason="RADAR_DADOS_REAIS nao definida")
def test_spark_deduplica_igual_a_referencia_em_python(spark, tmp_path):
    """No pico real, o Spark chega aos mesmos numeros que a contagem em Python."""
    from silver.processar import decodificados, deduplicar
    conteiner = Hora("2026-09-15", "10").conteiner(Path(REAIS) / "bronze_horario" / "vehicle_positions")
    df = decodificados(spark, [conteiner])
    referencia = taxa_de_duplicacao(l for n, pb in formato.ler(conteiner) for l in decodificar(n, pb))
    assert (df.count(), deduplicar(df).count()) == referencia[:2]


def test_vacuum_apaga_arquivos_antigos_e_nao_muda_a_tabela(spark, tmp_path):
    from silver.processar import limpar_versoes, processar_dia
    t = datetime(2026, 9, 15, 10, tzinfo=UTC)
    semear_bronze(tmp_path, {t: [{"id": "a", "ts": t}]})
    destino = str(tmp_path / "silver")
    dir_h = tmp_path / "bronze_horario" / "vehicle_positions"
    processar_dia(spark, date(2026, 9, 15), dir_h, destino)
    # Segunda carga do mesmo dia: o OPTIMIZE substitui os arquivos da primeira
    semear_bronze(tmp_path, {t + timedelta(hours=1): [{"id": "b", "ts": t + timedelta(hours=1)}]})
    processar_dia(spark, date(2026, 9, 15), dir_h, destino)
    antes = tabela(spark, destino)
    arquivos = lambda: len(list(Path(destino).rglob("*.parquet")))
    n = arquivos()

    limpar_versoes(spark, destino)  # sem nada com mais de 7 dias: nao apaga
    assert arquivos() == n

    spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "false")
    limpar_versoes(spark, destino, horas=0)
    spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "true")
    assert arquivos() == 1 < n
    assert tabela(spark, destino) == antes


def test_linha_de_comando_aceita_destino_relativo(spark, tmp_path, monkeypatch):
    """Achado no primeiro backfill: OPTIMIZE delta.`...` recusa caminho relativo,
    e os workers do Spark nao herdam a pasta corrente do driver."""
    from silver import processar
    t = datetime(2026, 9, 15, 10, tzinfo=UTC)
    semear_bronze(tmp_path, {t: [{"id": "a", "ts": t}]})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(processar, "sessao", lambda memoria="4g": spark)
    monkeypatch.setattr(spark, "stop", lambda: None)
    assert processar.main(["--de", "2026-09-15", "--ate", "2026-09-15", "--bronze", ".", "--destino", "silver"]) == 0
    assert spark.read.format("delta").load(str(tmp_path / "silver")).count() == 1


def test_hora_a_hora_da_o_mesmo_que_o_dia_inteiro(spark, tmp_path):
    """O Airflow grava uma hora por vez, e fora de ordem quando recupera atraso."""
    from silver.processar import processar_dia, processar_horas
    t = datetime(2026, 9, 15, 10, 59, 30, tzinfo=UTC)
    virada = t + timedelta(seconds=30)  # 11:00:00, outra hora
    semear_bronze(tmp_path, {
        t: [{"id": "a", "ts": t - timedelta(seconds=10)}, {"id": "b", "ts": t}],
        virada: [{"id": "a", "ts": t - timedelta(seconds=10)}, {"id": "b", "ts": virada}],
        virada + timedelta(hours=1): [{"id": "c", "ts": virada + timedelta(hours=1)}],
    })
    dir_h = tmp_path / "bronze_horario" / "vehicle_positions"
    dia = str(tmp_path / "dia")
    processar_dia(spark, date(2026, 9, 15), dir_h, dia)

    hora = str(tmp_path / "hora")
    for h in (Hora("2026-09-15", "12"), Hora("2026-09-15", "11"), Hora("2026-09-15", "10")):
        processar_horas(spark, [h], dir_h, hora, optimize=False)
    assert tabela(spark, hora) == tabela(spark, dia)
    # De novo, outra ordem: nada muda
    for h in (Hora("2026-09-15", "10"), Hora("2026-09-15", "11")):
        r = processar_horas(spark, [h], dir_h, hora, optimize=False)
        assert (r["inseridas"], r["atualizadas"]) == (0, 0)
    assert tabela(spark, hora) == tabela(spark, dia)


def test_hora_sem_conteiner_falha(spark, tmp_path, monkeypatch):
    from silver import processar
    monkeypatch.setattr(processar, "sessao", lambda memoria="4g": spark)
    monkeypatch.setattr(spark, "stop", lambda: None)
    destino = str(tmp_path / "silver")
    assert processar.main(["--hora", "2026-09-15T10", "--bronze", str(tmp_path), "--destino", destino]) == 1


def test_hora_e_janela_nao_vao_juntas():
    from silver import processar
    with pytest.raises(SystemExit):
        processar.main(["--hora", "2026-09-15T10", "--de", "2026-09-15", "--ate", "2026-09-15"])
    with pytest.raises(SystemExit):
        processar.main(["--de", "2026-09-15"])
