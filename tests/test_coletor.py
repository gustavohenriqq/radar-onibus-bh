from __future__ import annotations

import gzip
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from coletor.alerta import AvisoComIntervalo
from coletor.armazenamento import caminho_arquivo, gravar_atomico, mtime_mais_recente
from coletor.coletor import Coletor, espera_backoff, proximo_tick
from coletor.config import Config
from coletor.vigia import verificar

INSTANTE = datetime(2026, 8, 26, 14, 30, 0, tzinfo=timezone.utc)
PROTOBUF = {"Content-Type": "application/x-google-protobuf"}


class RespostaFalsa:
    def __init__(self, status=200, corpo=b"\x0a\x03feed", headers=None):
        self.status_code = status
        self.content = corpo
        self.headers = PROTOBUF if headers is None else headers


class SessaoFalsa:
    """Devolve respostas (ou levanta excecoes) na ordem dada."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.headers = {}
        self.chamadas = 0

    def get(self, url, timeout):
        self.chamadas += 1
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class CanalFalso:
    def __init__(self):
        self.mensagens: list[str] = []

    def enviar(self, texto):
        self.mensagens.append(texto)
        return True


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        url="http://exemplo.invalid/vehicle-positions",
        dir_dados=tmp_path / "dados",
        dir_log=tmp_path / "logs",
        intervalo_s=30,
        timeout_s=15,
        backoff_max_s=300,
        alerta_sem_arquivo_min=10,
        user_agent="teste",
        telegram_token=None,
        telegram_chat_id=None,
        healthcheck_url=None,
        healthcheck_compactacao_url=None,
        compactacao_folga_min=20,
        compactacao_quarentena_h=48,
        compactacao_nivel_zstd=3,
    )


def novo_coletor(cfg, *respostas):
    canal = CanalFalso()
    c = Coletor(cfg, sessao=SessaoFalsa(*respostas), alertas=AvisoComIntervalo(canal))
    return c, canal


# --- layout e gravacao -----------------------------------------------------

def test_caminho_segue_layout_particionado_em_utc(tmp_path):
    p = caminho_arquivo(tmp_path, INSTANTE)
    assert p.relative_to(tmp_path).as_posix() == "dt=2026-08-26/hh=14/20260826T143000Z.pb.gz"


def test_caminho_converte_horario_local_para_utc(tmp_path):
    from datetime import timedelta
    bh = timezone(timedelta(hours=-3))
    p = caminho_arquivo(tmp_path, datetime(2026, 8, 26, 23, 30, tzinfo=bh))
    assert p.relative_to(tmp_path).as_posix() == "dt=2026-08-27/hh=02/20260827T023000Z.pb.gz"


def test_gravacao_preserva_bytes_crus_e_nao_deixa_temporario(tmp_path):
    destino = caminho_arquivo(tmp_path, INSTANTE)
    gravar_atomico(destino, b"bytes crus")
    assert gzip.decompress(destino.read_bytes()) == b"bytes crus"
    assert [f.name for f in destino.parent.iterdir()] == [destino.name]


def test_gravacao_nunca_sobrescreve_bronze(tmp_path):
    destino = caminho_arquivo(tmp_path, INSTANTE)
    gravar_atomico(destino, b"original")
    with pytest.raises(FileExistsError):
        gravar_atomico(destino, b"outro")
    assert gzip.decompress(destino.read_bytes()) == b"original"


def test_gzip_deterministico(tmp_path):
    a = tmp_path / "a.pb.gz"
    b = tmp_path / "b.pb.gz"
    gravar_atomico(a, b"mesmo feed")
    gravar_atomico(b, b"mesmo feed")
    assert a.read_bytes() == b.read_bytes()


# --- agenda e backoff ------------------------------------------------------

def test_proximo_tick_alinha_ao_relogio():
    base = INSTANTE.timestamp()
    assert proximo_tick(base + 0.7, 30) == base + 30
    assert proximo_tick(base + 29.9, 30) == base + 30
    assert proximo_tick(base + 30, 30) == base + 60


def test_backoff_exponencial_com_teto():
    assert [espera_backoff(n, 30, 300) for n in range(1, 7)] == [30, 60, 120, 240, 300, 300]


# --- uma coleta -------------------------------------------------------------

def test_coleta_ok_grava_e_marca_repetida(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(), RespostaFalsa(), RespostaFalsa(corpo=b"outro"))
    r1 = c.coletar_uma_vez(INSTANTE)
    r2 = c.coletar_uma_vez(INSTANTE.replace(second=30))
    r3 = c.coletar_uma_vez(INSTANTE.replace(minute=31))
    assert r1.sucesso and r1.status == 200 and r1.repetida is False
    assert r2.sucesso and r2.repetida is True
    assert r3.sucesso and r3.repetida is False
    assert len(list(cfg.dir_bronze.rglob("*.pb.gz"))) == 3


def test_erro_de_rede_nao_levanta_e_nao_grava(cfg):
    c, _ = novo_coletor(cfg, requests.ConnectionError("caiu"))
    r = c.coletar_uma_vez(INSTANTE)
    assert not r.sucesso and r.erro.startswith("rede") and r.status is None
    assert not cfg.dir_bronze.exists()


@pytest.mark.parametrize("status", [401, 403])
def test_401_403_alerta_uma_vez_por_hora_e_avisa_recuperacao(cfg, status):
    c, canal = novo_coletor(cfg, RespostaFalsa(status=status), RespostaFalsa(status=status), RespostaFalsa())
    assert not c.coletar_uma_vez(INSTANTE).sucesso
    assert not c.coletar_uma_vez(INSTANTE.replace(second=30)).sucesso
    assert len(canal.mensagens) == 1 and f"HTTP {status}" in canal.mensagens[0]
    assert c.coletar_uma_vez(INSTANTE.replace(minute=31)).sucesso
    assert len(canal.mensagens) == 2 and "normalizado" in canal.mensagens[1]


def test_500_e_erro_comum_sem_alerta(cfg):
    c, canal = novo_coletor(cfg, RespostaFalsa(status=503))
    r = c.coletar_uma_vez(INSTANTE)
    assert r.erro == "http 503" and canal.mensagens == []


def test_200_que_nao_e_protobuf_nao_vira_bronze(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(corpo=b"<html>manutencao</html>", headers={"Content-Type": "text/html"}))
    r = c.coletar_uma_vez(INSTANTE)
    assert not r.sucesso and "content-type" in r.erro
    assert not cfg.dir_bronze.exists()


def test_200_vazio_nao_vira_bronze(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(corpo=b""))
    assert c.coletar_uma_vez(INSTANTE).erro == "corpo vazio"


def test_falha_de_disco_alerta_e_nao_levanta(cfg):
    c, canal = novo_coletor(cfg, RespostaFalsa(), RespostaFalsa())
    assert c.coletar_uma_vez(INSTANTE).sucesso
    r = c.coletar_uma_vez(INSTANTE)  # mesmo instante: arquivo ja existe
    assert not r.sucesso and r.erro.startswith("gravacao")
    assert len(canal.mensagens) == 1 and "disco" in canal.mensagens[0]


# --- vigia -----------------------------------------------------------------

def gravar_em(cfg, ts: float) -> None:
    """Grava um arquivo na particao de `ts` com mtime igual a `ts`, como
    aconteceria em producao, onde gravacao e particao sao do mesmo instante."""
    destino = caminho_arquivo(cfg.dir_bronze, datetime.fromtimestamp(ts, timezone.utc))
    gravar_atomico(destino, b"feed")
    os.utime(destino, (ts, ts))


def test_vigia_sem_arquivo_alerta_uma_vez_e_depois_avisa_volta(cfg):
    canal = CanalFalso()
    agora = INSTANTE.timestamp()
    assert verificar(cfg, canal, agora) is False
    assert verificar(cfg, canal, agora + 300) is False  # 5 min depois: sem repetir
    assert len(canal.mensagens) == 1
    assert verificar(cfg, canal, agora + 3600) is False  # lembrete de 1 h
    assert len(canal.mensagens) == 2

    gravar_em(cfg, agora + 3600)
    assert verificar(cfg, canal, agora + 3605) is True
    assert "voltou" in canal.mensagens[-1]


def test_vigia_detecta_atraso_acima_do_limite(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m)
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 9 * 60) is True
    assert verificar(cfg, canal, m + 11 * 60) is False
    assert len(canal.mensagens) == 1


def test_mtime_olha_hora_anterior_na_virada_de_hora(cfg):
    m = INSTANTE.replace(minute=59, second=30).timestamp()
    gravar_em(cfg, m)
    agora = INSTANTE.replace(hour=15, minute=2)
    assert mtime_mais_recente(cfg.dir_bronze, agora) == m
