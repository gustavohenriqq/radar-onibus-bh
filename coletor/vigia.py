"""Vigia: o unico processo que fala com o check `coletor-eventos`.

Uso: python -m coletor.vigia   (roda uma vez e sai; o systemd timer repete)

A cada 5 min ele procura quatro problemas, nesta ordem:

1. `chave`: a ultima coleta recebeu 401/403. A chave da URL mudou e nada mais
   sera gravado ate alguem trocar o .env.
2. `disco`: a ultima coleta falhou ao gravar.
3. `sem_arquivo`: nenhum arquivo novo ha mais de 10 min, por qualquer motivo.
4. `feed_parado`: chega arquivo, com status 200, mas a posicao de onibus mais
   nova tem mais de 10 min. E a queda do feed que a Gold mede em
   int_feed_parado: a frota inteira para de publicar e a API segue respondendo.

Os dois primeiros saem do log de coletas, que o coletor ja grava. Assim o
coletor nao fala com o check: com dois processos no mesmo check, o "ok" de um
apagaria o alerta do outro.

Com tudo bem, o vigia pinga sucesso: se o proprio vigia parar, o check vence
(1 h + 1 h) e avisa. Com problema, manda `/fail` com o motivo no corpo, uma vez
por motivo. O healthchecks nao repete a notificacao enquanto o check esta
fora, entao lembrete nao e preciso. Se o motivo muda com o check ja fora, o
vigia manda um ok antes do /fail novo, para a troca virar notificacao.

Limite conhecido: o vigia roda na mesma VM. Se a VM inteira cair, ele cai
junto. Para isso existe o HEALTHCHECK_URL do coletor (check externo).
"""

from __future__ import annotations

import gzip
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from coletor import registro
from coletor.alerta import Healthchecks
from coletor.armazenamento import caminho_arquivo, mtime_mais_recente
from coletor.config import Config

# Import no topo de proposito: sem o pacote na venv, o vigia tem que falhar
# alto (systemd mostra a falha), e nao ler cada arquivo como "ilegivel" e
# mandar um falso "feed parado".
from google.transit import gtfs_realtime_pb2 as gtfs

log =logging.getLogger("coletor")

ARQUIVO_COLETAS = "coletas.jsonl"
# 64 KB do fim do log: ~140 coletas, mais de uma hora. Basta a ultima.
CAUDA_BYTES = 64 * 1024
PREFIXO = "[coletor-onibus]"


@dataclass(frozen=True)
class Problema:
    motivo: str
    texto: str


def ultima_coleta(dir_log: Path) -> dict | None:
    """Ultima linha de coleta do log, lendo so o fim do arquivo."""
    caminho = dir_log / ARQUIVO_COLETAS
    try:
        with open(caminho, "rb") as f:
            f.seek(0, 2)
            tamanho = f.tell()
            f.seek(max(0, tamanho - CAUDA_BYTES))
            cauda = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for linha in reversed(cauda.splitlines()):
        try:
            evento = json.loads(linha)
        except ValueError:
            continue  # a primeira linha da cauda pode vir cortada
        if isinstance(evento, dict) and evento.get("evento") == "coleta":
            return evento
    return None


def _segundos(ts_iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(ts_iso).timestamp() if ts_iso else None
    except ValueError:
        return None


def arquivos_recentes(dir_bronze: Path, agora: datetime) -> list[Path]:
    """Arquivos da hora atual e da anterior, do mais novo para o mais velho.
    O nome e o instante da coleta, entao a ordem do nome e a do tempo."""
    utc = agora.astimezone(timezone.utc)
    arquivos: list[Path] = []
    for instante in (utc, datetime.fromtimestamp(utc.timestamp() - 3600, timezone.utc)):
        particao = caminho_arquivo(dir_bronze, instante).parent
        if particao.is_dir():
            arquivos.extend(particao.glob("*.pb.gz"))
    return sorted(arquivos, key=lambda p: p.name, reverse=True)


def posicao_mais_nova(protobuf: bytes) -> int | None:
    """Maior timestamp de veiculo no feed, em segundos Unix. None se o feed
    nao traz nenhuma posicao (a lista vazia do fim de uma queda).

    Decodifica so em memoria: o arquivo bronze nao e tocado."""
    feed = gtfs.FeedMessage()
    feed.ParseFromString(protobuf)
    tss = [e.vehicle.timestamp for e in feed.entity if e.HasField("vehicle") and e.vehicle.timestamp]
    return max(tss) if tss else None


def ultima_posicao(dir_bronze: Path, agora: datetime) -> int | None:
    """Posicao de onibus mais nova nas duas ultimas horas de arquivos.

    Para no primeiro arquivo que tiver posicao: no dia a dia le um arquivo so.
    Numa queda le de tras para frente ate achar a ultima posicao publicada."""
    mais_nova: int | None = None
    for arquivo in arquivos_recentes(dir_bronze, agora):
        try:
            ts = posicao_mais_nova(gzip.decompress(arquivo.read_bytes()))
        except Exception as e:  # arquivo ilegivel nao derruba o vigia
            log.warning("vigia_arquivo_ilegivel", extra={"campos": {"arquivo": arquivo.name, "erro": type(e).__name__}})
            continue
        if ts is not None:
            mais_nova = ts if mais_nova is None else max(mais_nova, ts)
            break
    return mais_nova


def diagnosticar(cfg: Config, agora: float) -> tuple[Problema | None, dict]:
    """Devolve o problema mais grave (ou None) e as medidas para o log."""
    agora_dt = datetime.fromtimestamp(agora, timezone.utc)
    limite_s = cfg.alerta_sem_arquivo_min * 60
    medidas: dict = {}

    coleta = ultima_coleta(cfg.dir_log)
    coleta_s = _segundos(coleta.get("ts")) if coleta else None
    # Coleta velha nao diz nada do agora: o coletor pode ter parado depois dela.
    recente = coleta if coleta_s is not None and agora - coleta_s <= limite_s else None
    if recente:
        medidas["ultima_status"] = recente.get("status")
        medidas["ultimo_erro"] = recente.get("erro")

    if recente and recente.get("status") in (401, 403):
        return Problema("chave", (
            f"{PREFIXO} HTTP {recente['status']} no feed. A chave de acesso provavelmente mudou. "
            "Confira https://dados.pbh.gov.br/dataset/gtfs-rt e atualize COLETOR_URL no .env."
        )), medidas
    if recente and str(recente.get("erro") or "").startswith("gravacao"):
        return Problema("disco", f"{PREFIXO} Falha ao gravar o arquivo (disco cheio ou com erro, ou arquivo do mesmo segundo ja existe): {recente['erro']}"), medidas

    ultimo = mtime_mais_recente(cfg.dir_bronze, agora_dt)
    atraso_s = None if ultimo is None else agora - ultimo
    medidas["atraso_s"] = None if atraso_s is None else round(atraso_s)
    if atraso_s is None or atraso_s > limite_s:
        detalhe = "nenhum arquivo nas ultimas 2 horas" if atraso_s is None else f"ultimo arquivo ha {round(atraso_s / 60)} min"
        if recente and recente.get("erro"):
            detalhe += f"; ultima coleta: {str(recente['erro'])[:200]}"
        elif coleta is None or recente is None:
            detalhe += "; coletor sem coleta no log nos ultimos minutos"
        return Problema("sem_arquivo", (
            f"{PREFIXO} Sem arquivo novo ha mais de {cfg.alerta_sem_arquivo_min} min ({detalhe}). "
            "Dado desse periodo esta sendo perdido."
        )), medidas

    posicao = ultima_posicao(cfg.dir_bronze, agora_dt)
    feed_s = None if posicao is None else agora - posicao
    medidas["feed_atraso_s"] = None if feed_s is None else round(feed_s)
    if feed_s is None or feed_s > cfg.alerta_feed_parado_min * 60:
        detalhe = "nenhuma posicao nas ultimas 2 horas" if feed_s is None else f"posicao mais nova ha {round(feed_s / 60)} min"
        return Problema("feed_parado", (
            f"{PREFIXO} Feed parado: a API responde 200, mas a frota nao publica posicao nova ({detalhe}). "
            "O coletor segue gravando; o periodo vira int_feed_parado na Gold."
        )), medidas
    return None, medidas


def _ler_estado(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar_estado(caminho: Path, estado: dict) -> None:
    # O estado mora em /dados. Com o disco cheio a gravacao falha, e o vigia
    # tem que seguir assim mesmo: no pior caso ele reenvia o /fail, e o
    # healthchecks nao notifica de novo um check que ja esta fora.
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(estado), encoding="utf-8")
    except OSError as e:
        log.error("vigia_estado_nao_gravado", extra={"campos": {"erro": type(e).__name__}})


def verificar(cfg: Config, canal: Healthchecks, agora: float | None = None) -> bool:
    """Devolve True se esta tudo bem. O estado em disco guarda o motivo ja
    avisado, para mandar um /fail por motivo e um aviso de volta."""
    agora = time.time() if agora is None else agora
    caminho_estado = cfg.dir_estado / "vigia.json"
    estado = _ler_estado(caminho_estado)

    problema, medidas = diagnosticar(cfg, agora)
    log.info("vigia", extra={"campos": {"ok": problema is None, "motivo": problema and problema.motivo, **medidas}})

    if problema is None:
        if estado.get("em_alerta"):
            if canal.ok(f"{PREFIXO} Voltou ao normal (era: {estado.get('motivo')})."):
                _gravar_estado(caminho_estado, {"em_alerta": False})
        else:
            canal.ok()
        return True

    if not estado.get("em_alerta") or estado.get("motivo") != problema.motivo:
        if estado.get("em_alerta"):
            # O healthchecks so notifica quando o check muda de estado. Um
            # /fail novo com o check ja fora so troca o corpo no painel, e
            # ninguem fica sabendo (ex.: disco enche durante uma queda do
            # feed). Um ok antes forca a volta e o novo alerta: 2 avisos.
            canal.ok(f"{PREFIXO} Motivo mudou: {estado.get('motivo')} -> {problema.motivo}.")
        if canal.falha(problema.texto):
            _gravar_estado(caminho_estado, {"em_alerta": True, "motivo": problema.motivo, "desde": agora})
    return False


def main() -> int:
    cfg = Config.do_ambiente()
    registro.configurar(cfg.dir_log, "vigia.jsonl")
    # Codigo de saida 1 com problema: aparece como falha no systemctl status.
    return 0 if verificar(cfg, Healthchecks(cfg.healthcheck_eventos_url)) else 1


if __name__ == "__main__":
    sys.exit(main())
