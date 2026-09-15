"""Loop de coleta do feed GTFS-Realtime vehicle-positions de Belo Horizonte.

Este processo fica fora do Airflow de proposito. Ele e o unico do sistema cuja
falha causa perda irreversivel: posicao de onibus que nao foi coletada nao
existe mais. Por isso ele e o mais simples possivel, sem dependencia de
scheduler, banco ou fila. Tudo que vem depois e reprocessavel e pode ser
orquestrado.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import requests

from coletor.alerta import AvisoComIntervalo, Telegram
from coletor.armazenamento import caminho_arquivo, gravar_atomico
from coletor.config import Config

log = logging.getLogger("coletor")


@dataclass
class ResultadoColeta:
    instante: str
    status: int | None = None
    bytes_resposta: int = 0
    bytes_gravados: int = 0
    latencia_ms: int | None = None
    sha256: str | None = None
    repetida: bool | None = None
    arquivo: str | None = None
    erro: str | None = None

    @property
    def sucesso(self) -> bool:
        return self.arquivo is not None


def proximo_tick(agora: float, intervalo_s: int) -> float:
    """Proximo multiplo do intervalo no relogio (ex.: :00 e :30).

    Alinhar ao relogio, em vez de dormir 30 s depois de cada coleta, evita
    deriva: a latencia de cada chamada nao se acumula, e os nomes de arquivo
    ficam previsiveis (143000Z, 143030Z), o que facilita achar lacunas.
    """
    return (int(agora // intervalo_s) + 1) * intervalo_s


def espera_backoff(falhas_seguidas: int, intervalo_s: int, maximo_s: int) -> float:
    """Backoff exponencial: 30, 60, 120, 240, 300, 300... segundos.

    Comeca no proprio intervalo, nunca abaixo dele. Retentar mais rapido que a
    cadencia normal seria martelar uma API publica gratuita justamente quando
    ela esta com problema. O teto de 5 min garante que, quando a API voltar,
    a coleta retoma em poucos minutos.
    """
    return float(min(intervalo_s * 2 ** (falhas_seguidas - 1), maximo_s))


class Coletor:
    def __init__(self, cfg: Config, sessao: requests.Session | None = None, alertas: AvisoComIntervalo | None = None):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self.sessao.headers["User-Agent"] = cfg.user_agent
        self.alertas = alertas or AvisoComIntervalo(Telegram(cfg.telegram_token, cfg.telegram_chat_id))
        self.parar = threading.Event()
        self._ultimo_sha: str | None = None
        self._falhas_seguidas = 0

    def coletar_uma_vez(self, instante: datetime) -> ResultadoColeta:
        r = ResultadoColeta(instante=instante.astimezone(timezone.utc).isoformat(timespec="seconds"))
        t0 = time.perf_counter()
        try:
            resp = self.sessao.get(self.cfg.url, timeout=self.cfg.timeout_s)
            corpo = resp.content
        except requests.RequestException as e:
            r.latencia_ms = round((time.perf_counter() - t0) * 1000)
            # Mensagem truncada: a do requests pode ser longa e trazer a URL,
            # mas o tipo sozinho nao distingue DNS, recusa e reset de conexao.
            r.erro = f"rede: {type(e).__name__}: {str(e)[:200]}"
            return r
        r.latencia_ms = round((time.perf_counter() - t0) * 1000)
        r.status = resp.status_code
        r.bytes_resposta = len(corpo)

        if resp.status_code in (401, 403):
            # 401/403 nao e instabilidade, e a chave da URL que mudou. Sem
            # alerta, o servico continua "rodando" e grava nada para sempre.
            r.erro = "acesso negado: chave da URL provavelmente rotacionada"
            self.alertas.avisar(
                "chave",
                f"[coletor-onibus] HTTP {resp.status_code} no feed. A chave de acesso "
                "provavelmente mudou. Confira https://dados.pbh.gov.br/dataset/gtfs-rt "
                "e atualize COLETOR_URL no .env.",
            )
            return r
        self.alertas.resolver("chave", "[coletor-onibus] Acesso ao feed normalizado.")

        if resp.status_code != 200:
            r.erro = f"http {resp.status_code}"
            return r
        if not corpo:
            r.erro = "corpo vazio"
            return r
        tipo = resp.headers.get("Content-Type", "")
        if "protobuf" not in tipo:
            # Um 200 com pagina HTML de erro ou manutencao nao e dado. Nao grava
            # como .pb.gz para nao poluir o bronze com arquivo que finge ser feed.
            r.erro = f"content-type inesperado: {tipo or 'ausente'}"
            return r

        # Nao decodifica e nao deduplica aqui. Medido em 14/09/2026: o feed
        # gera snapshot novo a cada ~20 s, entao parte das coletas devolve a
        # mesma resposta byte a byte. O coletor so marca a repeticao pelo hash
        # e grava mesmo assim: o bronze registra fielmente o que a API devolveu
        # em cada instante. A deduplicacao de verdade e por (vehicle_id,
        # timestamp) do proprio feed, na camada seguinte, onde e testavel.
        r.sha256 = hashlib.sha256(corpo).hexdigest()
        r.repetida = r.sha256 == self._ultimo_sha
        destino = caminho_arquivo(self.cfg.dir_bronze, instante)
        try:
            r.bytes_gravados = gravar_atomico(destino, corpo)
        except OSError as e:
            r.erro = f"gravacao: {type(e).__name__}: {e}"
            self.alertas.avisar("disco", f"[coletor-onibus] Falha ao gravar no disco: {type(e).__name__}: {e}")
            return r
        self.alertas.resolver("disco", "[coletor-onibus] Gravacao em disco normalizada.")
        self._ultimo_sha = r.sha256
        r.arquivo = str(destino)
        return r

    def _ping_healthcheck(self) -> None:
        # Dead man's switch externo: o servico de fora alerta quando os pings
        # param. Cobre o que nenhum vigia local cobre: a VM inteira fora do ar.
        if not self.cfg.healthcheck_url:
            return
        try:
            self.sessao.get(self.cfg.healthcheck_url, timeout=10)
        except requests.RequestException as e:
            log.warning("healthcheck_falhou", extra={"campos": {"erro": type(e).__name__}})

    def executar(self) -> None:
        log.info("inicio", extra={"campos": {"intervalo_s": self.cfg.intervalo_s, "dir_bronze": str(self.cfg.dir_bronze)}})
        proxima = proximo_tick(time.time(), self.cfg.intervalo_s)
        ultimo_ping = 0.0
        while not self.parar.wait(max(0.0, proxima - time.time())):
            try:
                r = self.coletar_uma_vez(datetime.now(timezone.utc))
            except Exception:
                # Rede de seguranca: qualquer bug nao previsto vira log e
                # backoff, nunca a morte do processo. O systemd com
                # Restart=always e a segunda camada, nao a primeira.
                log.exception("erro_inesperado")
                r = ResultadoColeta(instante=datetime.now(timezone.utc).isoformat(timespec="seconds"), erro="erro inesperado")

            nivel = logging.INFO if r.sucesso else logging.WARNING
            log.log(nivel, "coleta", extra={"campos": asdict(r)})

            agora = time.time()
            if r.sucesso:
                self._falhas_seguidas = 0
                proxima = proximo_tick(agora, self.cfg.intervalo_s)
                if agora - ultimo_ping >= 60:
                    self._ping_healthcheck()
                    ultimo_ping = agora
            else:
                self._falhas_seguidas += 1
                proxima = agora + espera_backoff(self._falhas_seguidas, self.cfg.intervalo_s, self.cfg.backoff_max_s)
        log.info("fim")
