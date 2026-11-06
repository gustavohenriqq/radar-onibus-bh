from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from coletor.alerta import Healthchecks
from coletor.armazenamento import caminho_arquivo, gravar_atomico, mtime_mais_recente
from coletor.coletor import Coletor, espera_backoff, proximo_tick
from coletor.config import Config
from coletor.vigia import posicao_mais_nova, ultima_coleta, verificar

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
    """Faz o papel do check: guarda cada ping como (tipo, texto)."""

    def __init__(self, funciona=True):
        self.pings: list[tuple[str, str]] = []
        self.funciona = funciona

    def ok(self, texto=""):
        self.pings.append(("ok", texto))
        return self.funciona

    def falha(self, texto):
        self.pings.append(("fail", texto))
        return self.funciona

    @property
    def falhas(self):
        return [t for tipo, t in self.pings if tipo == "fail"]


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
        healthcheck_url=None,
        healthcheck_compactacao_url=None,
        compactacao_folga_min=20,
        compactacao_quarentena_h=48,
        compactacao_nivel_zstd=3,
    )


def novo_coletor(cfg, *respostas):
    return Coletor(cfg, sessao=SessaoFalsa(*respostas)), None


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
def test_401_403_registra_status_e_nao_grava(cfg, status):
    c, _ = novo_coletor(cfg, RespostaFalsa(status=status), RespostaFalsa())
    r = c.coletar_uma_vez(INSTANTE)
    assert not r.sucesso and r.status == status and "acesso negado" in r.erro
    assert not cfg.dir_bronze.exists()
    assert c.coletar_uma_vez(INSTANTE.replace(minute=31)).sucesso


def test_500_e_erro_comum(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(status=503))
    assert c.coletar_uma_vez(INSTANTE).erro == "http 503"


def test_200_que_nao_e_protobuf_nao_vira_bronze(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(corpo=b"<html>manutencao</html>", headers={"Content-Type": "text/html"}))
    r = c.coletar_uma_vez(INSTANTE)
    assert not r.sucesso and "content-type" in r.erro
    assert not cfg.dir_bronze.exists()


def test_200_vazio_nao_vira_bronze(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(corpo=b""))
    assert c.coletar_uma_vez(INSTANTE).erro == "corpo vazio"


def test_falha_de_disco_vira_erro_gravacao_e_nao_levanta(cfg):
    c, _ = novo_coletor(cfg, RespostaFalsa(), RespostaFalsa())
    assert c.coletar_uma_vez(INSTANTE).sucesso
    r = c.coletar_uma_vez(INSTANTE)  # mesmo instante: arquivo ja existe
    assert not r.sucesso and r.erro.startswith("gravacao")


# --- vigia -----------------------------------------------------------------

def feed(*timestamps_veiculo: int, cabecalho: int = 0) -> bytes:
    """FeedMessage real com um veiculo por timestamp (0 = sem timestamp)."""
    from google.transit import gtfs_realtime_pb2 as gtfs

    f = gtfs.FeedMessage()
    f.header.gtfs_realtime_version = "2.0"
    f.header.timestamp = cabecalho
    for n, ts in enumerate(timestamps_veiculo):
        e = f.entity.add()
        e.id = str(n)
        e.vehicle.vehicle.id = f"v{n}"
        if ts:
            e.vehicle.timestamp = ts
    return f.SerializeToString()


def gravar_em(cfg, ts: float, posicao: float | None = None, corpo: bytes | None = None) -> None:
    """Grava um arquivo na particao de `ts` com mtime igual a `ts`, como em
    producao. Por padrao a posicao do onibus e 40 s antes da coleta, a
    defasagem mediana medida na Silver."""
    destino = caminho_arquivo(cfg.dir_bronze, datetime.fromtimestamp(ts, timezone.utc))
    if corpo is None:
        corpo = feed(int(ts - 40 if posicao is None else posicao), cabecalho=int(ts))
    gravar_atomico(destino, corpo)
    os.utime(destino, (ts, ts))


def logar_coleta(cfg, ts: float, status=200, erro=None) -> None:
    """Linha no formato de registro.FormatoJson, como o coletor grava."""
    cfg.dir_log.mkdir(parents=True, exist_ok=True)
    linha = {"ts": datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds"),
             "nivel": "INFO", "evento": "coleta", "status": status, "erro": erro}
    with open(cfg.dir_log / "coletas.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(linha) + "\n")


def test_vigia_tudo_ok_pinga_sucesso_a_cada_rodada(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m)
    logar_coleta(cfg, m)
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 30) is True
    assert verificar(cfg, canal, m + 330) is True  # 5,5 min: ainda dentro dos 10
    assert canal.pings == [("ok", ""), ("ok", "")]


def test_vigia_sem_arquivo_manda_um_fail_e_depois_avisa_volta(cfg):
    canal = CanalFalso()
    agora = INSTANTE.timestamp()
    assert verificar(cfg, canal, agora) is False
    assert verificar(cfg, canal, agora + 300) is False  # mesmo motivo: sem repetir
    assert verificar(cfg, canal, agora + 3600) is False
    assert len(canal.falhas) == 1 and "Sem arquivo novo" in canal.falhas[0]

    gravar_em(cfg, agora + 3600)
    assert verificar(cfg, canal, agora + 3605) is True
    assert canal.pings[-1][0] == "ok" and "sem_arquivo" in canal.pings[-1][1]


def test_vigia_detecta_atraso_acima_do_limite_e_cita_o_erro(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m)
    logar_coleta(cfg, m + 600, status=None, erro="rede: ConnectionError: Read timed out.")
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 9 * 60) is True
    assert verificar(cfg, canal, m + 11 * 60) is False
    assert len(canal.falhas) == 1 and "Read timed out" in canal.falhas[0]


@pytest.mark.parametrize("status", [401, 403])
def test_vigia_401_403_alerta_na_hora_mesmo_com_arquivo_recente(cfg, status):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m)
    logar_coleta(cfg, m)
    logar_coleta(cfg, m + 30, status=status, erro="acesso negado: chave da URL provavelmente rotacionada")
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 60) is False
    assert len(canal.falhas) == 1 and f"HTTP {status}" in canal.falhas[0] and "COLETOR_URL" in canal.falhas[0]

    gravar_em(cfg, m + 120)
    logar_coleta(cfg, m + 120)
    assert verificar(cfg, canal, m + 150) is True
    assert "chave" in canal.pings[-1][1]


def test_vigia_falha_de_disco(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m)
    logar_coleta(cfg, m + 30, status=200, erro="gravacao: OSError: [Errno 28] No space left on device")
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 60) is False
    assert "disco" in canal.falhas[0] and "Errno 28" in canal.falhas[0]


def test_vigia_troca_de_motivo_manda_novo_fail(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m)
    logar_coleta(cfg, m + 30, status=401, erro="acesso negado")
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 60) is False
    # 20 min de 401: o log continua com 401, entao o motivo continua "chave"
    logar_coleta(cfg, m + 1200, status=401, erro="acesso negado")
    assert verificar(cfg, canal, m + 1210) is False
    assert len(canal.falhas) == 1
    # o coletor para de registrar: sobra so o "sem arquivo"
    assert verificar(cfg, canal, m + 1900) is False
    assert len(canal.falhas) == 2 and "Sem arquivo novo" in canal.falhas[1]
    # o ok antes do /fail novo forca o healthchecks a notificar a troca
    assert canal.pings[-2][0] == "ok" and "chave -> sem_arquivo" in canal.pings[-2][1]


def test_vigia_coleta_velha_no_log_nao_conta(cfg):
    m = INSTANTE.timestamp()
    logar_coleta(cfg, m, status=401, erro="acesso negado")
    gravar_em(cfg, m + 3000)
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 3030) is True  # o 401 foi ha 50 min


def test_vigia_feed_parado_com_posicoes_congeladas(cfg):
    m = INSTANTE.timestamp()
    congelada = m - 60
    for k in range(0, 15 * 60, 30):  # 15 min de arquivos com a mesma posicao
        gravar_em(cfg, m + k, posicao=congelada)
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 8 * 60) is True
    assert verificar(cfg, canal, m + 15 * 60) is False
    assert "Feed parado" in canal.falhas[0] and "16 min" in canal.falhas[0]


def test_vigia_feed_parado_com_lista_vazia_acha_a_ultima_posicao(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m, posicao=m - 40)
    for k in range(30, 20 * 60, 30):
        gravar_em(cfg, m + k, corpo=feed(cabecalho=int(m + k)))  # cabecalho anda, lista vazia
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 20 * 60) is False
    assert "posicao mais nova ha 21 min" in canal.falhas[0]

    gravar_em(cfg, m + 20 * 60 + 30)  # frota volta a publicar
    assert verificar(cfg, canal, m + 20 * 60 + 40) is True
    assert "feed_parado" in canal.pings[-1][1]


def test_vigia_feed_sem_nenhuma_posicao_em_2_horas(cfg):
    m = INSTANTE.timestamp()
    gravar_em(cfg, m, corpo=feed(cabecalho=int(m)))
    canal = CanalFalso()
    assert verificar(cfg, canal, m + 30) is False
    assert "nenhuma posicao nas ultimas 2 horas" in canal.falhas[0]


def test_vigia_ping_que_falha_tenta_de_novo_na_rodada_seguinte(cfg):
    canal = CanalFalso(funciona=False)
    agora = INSTANTE.timestamp()
    assert verificar(cfg, canal, agora) is False
    assert verificar(cfg, canal, agora + 300) is False
    assert len(canal.falhas) == 2  # o estado so avanca quando o ping chega


def test_posicao_mais_nova_ignora_veiculo_sem_timestamp():
    assert posicao_mais_nova(feed(100, 0, 300, 200)) == 300
    assert posicao_mais_nova(feed(0, 0)) is None
    assert posicao_mais_nova(feed()) is None


def test_ultima_coleta_le_so_o_fim_e_ignora_linha_cortada(cfg):
    cfg.dir_log.mkdir(parents=True)
    with open(cfg.dir_log / "coletas.jsonl", "w", encoding="utf-8") as f:
        f.write("x" * 200_000 + "\n")  # linha gigante: a cauda comeca no meio dela
        f.write(json.dumps({"ts": "2026-08-26T14:30:00+00:00", "evento": "coleta", "status": 200}) + "\n")
        f.write(json.dumps({"ts": "2026-08-26T14:30:01+00:00", "evento": "outro"}) + "\n")
    assert ultima_coleta(cfg.dir_log)["status"] == 200
    assert ultima_coleta(cfg.dir_log / "nao_existe") is None


class RespostaOk:
    def raise_for_status(self):
        pass


class SessaoPost:
    def __init__(self, erro=None):
        self.chamadas = []
        self.erro = erro

    def post(self, url, data, timeout):
        self.chamadas.append((url, data))
        if self.erro:
            raise self.erro
        return RespostaOk()


def test_healthchecks_ok_e_fail_com_corpo():
    s = SessaoPost()
    hc = Healthchecks("https://hc-ping.com/abc/", sessao=s)
    assert hc.ok() and hc.falha("HTTP 401 no feed")
    assert s.chamadas == [("https://hc-ping.com/abc", b""), ("https://hc-ping.com/abc/fail", b"HTTP 401 no feed")]


def test_healthchecks_sem_url_ou_com_erro_nao_levanta():
    assert Healthchecks(None).falha("x") is False
    assert Healthchecks("https://hc-ping.com/abc", sessao=SessaoPost(requests.ConnectionError("caiu"))).falha("x") is False


def test_mtime_olha_hora_anterior_na_virada_de_hora(cfg):
    m = INSTANTE.replace(minute=59, second=30).timestamp()
    gravar_em(cfg, m)
    agora = INSTANTE.replace(hour=15, minute=2)
    assert mtime_mais_recente(cfg.dir_bronze, agora) == m
