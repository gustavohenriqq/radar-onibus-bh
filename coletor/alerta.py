"""Envio de alerta pelo Telegram.

Por que Telegram: gratuito, chega no celular na hora e e um POST HTTP, sem
servidor de e-mail nem risco de cair no spam.

Regra: falha ao alertar nunca derruba o coletor. O alerta e acessorio, a
coleta e o que nao pode parar.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("coletor")


class Telegram:
    def __init__(self, token: str | None, chat_id: str | None, sessao: requests.Session | None = None):
        self.token = token
        self.chat_id = chat_id
        self.sessao = sessao or requests.Session()

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat_id)

    def enviar(self, texto: str) -> bool:
        if not self.configurado:
            log.warning("alerta_nao_configurado", extra={"campos": {"texto": texto}})
            return False
        try:
            r = self.sessao.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": texto},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            # Nao loga a URL: ela contem o token do bot.
            log.error("alerta_falhou", extra={"campos": {"erro": type(e).__name__, "texto": texto}})
            return False


class AvisoComIntervalo:
    """Evita inundar o celular: um problema que persiste gera um alerta na
    primeira ocorrencia, um lembrete por intervalo, e um aviso de recuperacao
    quando volta ao normal."""

    def __init__(self, canal: Telegram, lembrete_s: int = 3600, relogio=time.time):
        self.canal = canal
        self.lembrete_s = lembrete_s
        self.relogio = relogio
        self._ativos: dict[str, float] = {}

    def avisar(self, chave: str, texto: str) -> bool:
        agora = self.relogio()
        ultimo = self._ativos.get(chave)
        if ultimo is not None and agora - ultimo < self.lembrete_s:
            return False
        self._ativos[chave] = agora
        return self.canal.enviar(texto)

    def resolver(self, chave: str, texto: str) -> bool:
        if chave not in self._ativos:
            return False
        del self._ativos[chave]
        return self.canal.enviar(texto)
