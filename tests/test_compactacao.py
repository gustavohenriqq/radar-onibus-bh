from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from coletor.armazenamento import caminho_arquivo, gravar_atomico
from coletor.config import Config
from compactacao import formato
from compactacao.compactar import compactar_hora
from compactacao.horas import Hora, conteiner_valido, fechada, horas_com_dado, pendentes
from compactacao.limpar import limpar_hora

HORA = Hora("2026-09-15", "10")
DEPOIS = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        url="", dir_dados=tmp_path / "dados", dir_log=tmp_path / "logs",
        intervalo_s=30, timeout_s=15, backoff_max_s=300, alerta_sem_arquivo_min=10,
        user_agent="teste", telegram_token=None, telegram_chat_id=None,
        healthcheck_url=None, healthcheck_compactacao_url=None,
        compactacao_folga_min=20, compactacao_quarentena_h=48, compactacao_nivel_zstd=3,
    )


def semear(cfg: Config, hora: Hora = HORA, n: int = 5, conteudo=lambda i: b"protobuf-%d" % i) -> list[Path]:
    """Grava n coletas pelo mesmo caminho que o coletor usa em producao."""
    criados = []
    base = hora.inicio
    for i in range(n):
        destino = caminho_arquivo(cfg.dir_bronze, base + timedelta(seconds=30 * i))
        gravar_atomico(destino, conteudo(i))
        criados.append(destino)
    return criados


# --- formato do conteiner ---------------------------------------------------

def test_conteiner_reconstroi_o_original_byte_a_byte(cfg):
    origens = semear(cfg, n=4)
    originais = {p.name: p.read_bytes() for p in origens}
    destino = HORA.conteiner(cfg.dir_bronze_horario)
    r = formato.escrever(destino, origens, nivel=3)
    assert r.coletas == 4
    refeitos = {f"{nome}.pb.gz": formato.reconstruir_gz(pb) for nome, pb in formato.ler(destino)}
    assert refeitos == originais


def test_conteiner_e_menor_que_a_soma_dos_originais(cfg):
    # conteudo repetitivo, como o feed real: o zstd aproveita a redundancia
    # entre coletas, que o gzip por arquivo nao enxerga
    origens = semear(cfg, n=30, conteudo=lambda i: b"veiculo-1234-posicao" * 200 + bytes([i]))
    destino = HORA.conteiner(cfg.dir_bronze_horario)
    r = formato.escrever(destino, origens, nivel=3)
    assert r.bytes_conteiner < sum(p.stat().st_size for p in origens)


def test_cabecalho_errado_e_recusado(cfg, tmp_path):
    ruim = tmp_path / "ruim.pb.zst"
    import zstandard as zstd
    ruim.write_bytes(zstd.ZstdCompressor().compress(b"OUTRO\nlixo"))
    with pytest.raises(ValueError, match="cabecalho invalido"):
        list(formato.ler(ruim))


def test_conteiner_truncado_e_detectado(cfg):
    origens = semear(cfg, n=5)
    destino = HORA.conteiner(cfg.dir_bronze_horario)
    formato.escrever(destino, origens, nivel=3)
    dados = destino.read_bytes()
    destino.write_bytes(dados[: len(dados) // 2])
    with pytest.raises(Exception):
        list(formato.ler(destino))


# --- selecao de horas -------------------------------------------------------

def test_hora_so_fecha_depois_do_fim_mais_a_folga():
    assert not fechada(HORA, datetime(2026, 9, 15, 10, 59, tzinfo=timezone.utc), 20)
    assert not fechada(HORA, datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc), 20)
    assert not fechada(HORA, datetime(2026, 9, 15, 11, 19, tzinfo=timezone.utc), 20)
    assert fechada(HORA, datetime(2026, 9, 15, 11, 20, tzinfo=timezone.utc), 20)


def test_hora_em_andamento_nao_entra_na_fila(cfg):
    semear(cfg)
    agora = datetime(2026, 9, 15, 10, 40, tzinfo=timezone.utc)
    assert pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, agora, 20) == []


def test_backfill_pega_todas_as_horas_fechadas_sem_conteiner(cfg):
    for hh in ("08", "09", "10"):
        semear(cfg, Hora("2026-09-15", hh), n=3)
    fila = pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, DEPOIS, 20)
    assert [h.hh for h in fila] == ["08", "09", "10"]


def test_particao_vazia_e_ignorada(cfg):
    (cfg.dir_bronze / "dt=2026-09-15" / "hh=03").mkdir(parents=True)
    assert horas_com_dado(cfg.dir_bronze) == []


# --- idempotencia -----------------------------------------------------------

def test_rodar_duas_vezes_nao_duplica_nem_muda_o_arquivo(cfg):
    semear(cfg, n=6)
    r1 = compactar_hora(HORA, cfg)
    bytes1 = HORA.conteiner(cfg.dir_bronze_horario).read_bytes()
    assert pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, DEPOIS, 20) == []  # segunda execucao pularia
    r2 = compactar_hora(HORA, cfg)  # forcando mesmo assim
    assert r2["coletas"] == r1["coletas"] == 6
    assert HORA.conteiner(cfg.dir_bronze_horario).read_bytes() == bytes1  # zstd deterministico
    assert len(list(formato.ler(HORA.conteiner(cfg.dir_bronze_horario)))) == 6


def test_conteiner_corrompido_volta_para_a_fila(cfg):
    semear(cfg, n=4)
    compactar_hora(HORA, cfg)
    alvo = HORA.conteiner(cfg.dir_bronze_horario)
    alvo.write_bytes(alvo.read_bytes()[:-50])
    ok, motivo = conteiner_valido(HORA, cfg.dir_bronze_horario, cfg.dir_bronze)
    assert not ok and "sha256" in motivo or "tamanho" in motivo
    assert pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, DEPOIS, 20) == [HORA]


def test_coleta_atrasada_depois_da_compactacao_forca_reprocesso(cfg):
    semear(cfg, n=3)
    compactar_hora(HORA, cfg)
    assert pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, DEPOIS, 20) == []
    gravar_atomico(caminho_arquivo(cfg.dir_bronze, HORA.inicio + timedelta(minutes=59)), b"atrasada")
    ok, motivo = conteiner_valido(HORA, cfg.dir_bronze_horario, cfg.dir_bronze)
    assert not ok and "manifesto" in motivo
    assert pendentes(cfg.dir_bronze, cfg.dir_bronze_horario, DEPOIS, 20) == [HORA]
    assert compactar_hora(HORA, cfg)["coletas"] == 4


def test_manifesto_tem_o_que_a_limpeza_precisa(cfg):
    origens = semear(cfg, n=3)
    compactar_hora(HORA, cfg)
    m = json.loads(HORA.manifesto(cfg.dir_bronze_horario).read_text())
    assert m["versao_formato"] == 1 and m["coletas"] == 3
    assert m["sha256_conteiner"] == formato.sha256_arquivo(HORA.conteiner(cfg.dir_bronze_horario))
    for p in origens:
        assert m["sha256_originais"][p.name] == hashlib.sha256(p.read_bytes()).hexdigest()


def test_escrita_atomica_nao_deixa_temporario(cfg):
    semear(cfg, n=3)
    compactar_hora(HORA, cfg)
    assert list(HORA.conteiner(cfg.dir_bronze_horario).parent.glob(".*")) == []


# --- limpeza ----------------------------------------------------------------

def test_limpeza_apaga_so_depois_de_conferir(cfg):
    origens = semear(cfg, n=5)
    compactar_hora(HORA, cfg)
    r = limpar_hora(HORA, cfg, seco=False)
    assert r["apagados"] == 5 and r["conferidas"] == 5
    assert not HORA.dir_origem(cfg.dir_bronze).exists()
    # o dado continua recuperavel
    refeitos = list(formato.ler(HORA.conteiner(cfg.dir_bronze_horario)))
    assert len(refeitos) == 5
    assert gzip.decompress(formato.reconstruir_gz(refeitos[0][1])) == b"protobuf-0"


def test_modo_seco_nao_apaga_nada(cfg):
    semear(cfg, n=4)
    compactar_hora(HORA, cfg)
    r = limpar_hora(HORA, cfg, seco=True)
    assert r["apagados"] == 4
    assert len(list(HORA.dir_origem(cfg.dir_bronze).glob("*.pb.gz"))) == 4


def test_limpeza_recusa_apagar_se_o_original_mudou(cfg):
    origens = semear(cfg, n=4)
    compactar_hora(HORA, cfg)
    origens[2].write_bytes(b"conteudo trocado por engano")
    with pytest.raises(RuntimeError, match="hash diferente"):
        limpar_hora(HORA, cfg, seco=False)
    assert len(list(HORA.dir_origem(cfg.dir_bronze).glob("*.pb.gz"))) == 4  # nada apagado


def test_limpeza_recusa_arquivo_que_nao_esta_no_conteiner(cfg):
    semear(cfg, n=3)
    compactar_hora(HORA, cfg)
    gravar_atomico(caminho_arquivo(cfg.dir_bronze, HORA.inicio + timedelta(minutes=30)), b"nova")
    with pytest.raises(RuntimeError, match="fora do conteiner"):
        limpar_hora(HORA, cfg, seco=False)
    assert len(list(HORA.dir_origem(cfg.dir_bronze).glob("*.pb.gz"))) == 4


def test_limpeza_e_idempotente(cfg):
    semear(cfg, n=3)
    compactar_hora(HORA, cfg)
    assert limpar_hora(HORA, cfg, seco=False)["apagados"] == 3
    HORA.dir_origem(cfg.dir_bronze).mkdir(parents=True, exist_ok=True)
    assert limpar_hora(HORA, cfg, seco=False)["apagados"] == 0
