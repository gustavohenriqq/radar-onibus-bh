from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest

from backup import enviar, restaurar
from backup.remoto import Remoto
from coletor.config import Config
from coletor.armazenamento import caminho_arquivo, gravar_atomico
from compactacao.compactar import compactar_hora
from compactacao.horas import Hora
from tests.test_compactacao import semear

URL = "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOKEN/n/ns/b/backup/o/"
DIA = "2026-09-15"
AGORA = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)


class Resposta:
    def __init__(self, status: int, corpo: bytes = b""):
        self.status_code, self._corpo = status, corpo

    def iter_content(self, tamanho):
        for i in range(0, len(self._corpo), tamanho):
            yield self._corpo[i:i + tamanho]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class BucketFalso:
    """Imita o que importa do Object Storage com PAR e regra de retencao:
    PUT cria, PUT sobre objeto existente e recusado, nao ha DELETE."""

    def __init__(self, corromper: str | None = None):
        self.objetos: dict[str, bytes] = {}
        self.puts = 0
        self.corromper = corromper

    def put(self, url, data, timeout, headers):
        self.puts += 1
        nome = unquote(url[len(URL):])  # o servidor decodifica o caminho
        if nome in self.objetos:
            return Resposta(409)
        corpo = data.read()
        if self.corromper and nome.endswith(self.corromper):
            corpo = corpo[:-10]
        self.objetos[nome] = corpo
        return Resposta(200)

    def get(self, url, stream, timeout):
        nome = unquote(url[len(URL):])  # o servidor decodifica o caminho
        if nome not in self.objetos:
            return Resposta(404)
        return Resposta(200, self.objetos[nome])


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        url="", dir_dados=tmp_path / "dados", dir_log=tmp_path / "logs",
        intervalo_s=30, timeout_s=15, backoff_max_s=300, alerta_sem_arquivo_min=10,
        user_agent="teste", telegram_token=None, telegram_chat_id=None,
        healthcheck_url=None, healthcheck_compactacao_url=None,
        compactacao_folga_min=20, compactacao_quarentena_h=48, compactacao_nivel_zstd=3,
    )


def lake(cfg: Config, horas=("09", "10", "11")) -> dict[str, bytes]:
    """Compacta algumas horas pelo caminho de producao e devolve os originais."""
    originais = {}
    for hh in horas:
        hora = Hora(DIA, hh)
        for p in semear(cfg, hora, n=4, conteudo=lambda i, hh=hh: b"feed-%s-%d" % (hh.encode(), i) * 50):
            originais[f"dt={DIA}/hh={hh}/{p.name}"] = p.read_bytes()
        compactar_hora(hora, cfg)
    return originais


def test_url_tem_que_ser_da_par_do_bucket():
    with pytest.raises(ValueError):
        Remoto("https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOKEN/n/ns/b/backup/")


def test_backup_envia_e_confere_todas_as_horas(cfg):
    lake(cfg)
    bucket = BucketFalso()
    enviadas, em_dia, falhas = enviar.executar(cfg, Remoto(URL, bucket), AGORA)
    assert (enviadas, em_dia, falhas) == (3, 0, 0)
    for hh in ("09", "10", "11"):
        local = Hora(DIA, hh).conteiner(cfg.dir_bronze_horario)
        assert bucket.objetos[enviar.nome_objeto(local, cfg)] == local.read_bytes()
    # nome no bucket espelha o caminho em /dados, para restaurar sem traducao
    assert "bronze_horario/vehicle_positions/dt=2026-09-15/vp_20260915T10.pb.zst" in bucket.objetos


def test_rodar_de_novo_nao_reenvia_nada(cfg):
    lake(cfg)
    bucket = BucketFalso()
    enviar.executar(cfg, Remoto(URL, bucket), AGORA)
    puts = bucket.puts
    assert enviar.executar(cfg, Remoto(URL, bucket), AGORA) == (0, 3, 0)
    assert bucket.puts == puts


def test_estado_perdido_confere_o_que_ja_esta_no_bucket(cfg):
    lake(cfg)
    bucket = BucketFalso()
    enviar.executar(cfg, Remoto(URL, bucket), AGORA)
    antes = dict(bucket.objetos)
    (cfg.dir_estado / "backup.json").unlink()
    # o bucket recusa a sobrescrita (409) e o job confere o que ja esta la
    assert enviar.executar(cfg, Remoto(URL, bucket), AGORA) == (3, 0, 0)
    assert bucket.objetos == antes


def test_objeto_corrompido_no_envio_vira_falha_e_nao_entra_no_estado(cfg):
    lake(cfg, horas=("10",))
    bucket = BucketFalso(corromper=".pb.zst")
    assert enviar.executar(cfg, Remoto(URL, bucket), AGORA) == (0, 0, 1)
    assert enviar.ler_estado(cfg.dir_estado / "backup.json") == {}


def test_conteiner_que_mudou_depois_do_backup_vira_falha(cfg):
    lake(cfg, horas=("10",))
    bucket = BucketFalso()
    enviar.executar(cfg, Remoto(URL, bucket), AGORA)
    original = dict(bucket.objetos)
    # simula uma coleta atrasada que faz a compactacao refazer a hora
    atrasada = caminho_arquivo(cfg.dir_bronze, Hora(DIA, "10").inicio + timedelta(minutes=30))
    gravar_atomico(atrasada, b"coleta atrasada")
    compactar_hora(Hora(DIA, "10"), cfg)
    assert enviar.executar(cfg, Remoto(URL, bucket), AGORA)[2] == 1
    assert bucket.objetos == original


def test_hora_recente_espera_a_folga(cfg):
    lake(cfg, horas=("10", "11"))
    # 13:30 com folga de 2 h: a hora 10 (fim 11:00) entra, a 11 (fim 12:00) espera
    agora = datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc)
    assert enviar.executar(cfg, Remoto(URL, BucketFalso()), agora) == (1, 0, 0)


def test_restauracao_de_um_dia_devolve_os_originais_byte_a_byte(cfg, tmp_path, monkeypatch):
    originais = lake(cfg)
    bucket = BucketFalso()
    enviar.executar(cfg, Remoto(URL, bucket), AGORA)
    monkeypatch.setattr(restaurar, "Remoto", lambda url: Remoto(URL, bucket))
    monkeypatch.setenv("BACKUP_PAR_URL", URL)
    destino = tmp_path / "restauro"
    assert restaurar.main(["--dia", DIA, "--destino", str(destino), "--originais"]) == 0
    base = destino / "bronze" / "vehicle_positions"
    refeitos = {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*.pb.gz")}
    assert refeitos == originais


def test_restauracao_detecta_conteiner_adulterado_no_bucket(cfg, tmp_path, monkeypatch):
    lake(cfg, horas=("10",))
    bucket = BucketFalso()
    enviar.executar(cfg, Remoto(URL, bucket), AGORA)
    nome = "bronze_horario/vehicle_positions/dt=2026-09-15/vp_20260915T10.pb.zst"
    bucket.objetos[nome] = bucket.objetos[nome][:-1] + b"\x00"
    monkeypatch.setattr(restaurar, "Remoto", lambda url: Remoto(URL, bucket))
    monkeypatch.setenv("BACKUP_PAR_URL", URL)
    assert restaurar.main(["--dia", DIA, "--destino", str(tmp_path / "r")]) == 1
