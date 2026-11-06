"""Envio de alerta pelo check `coletor-eventos` do healthchecks.io.

Por que healthchecks e nao um bot do Telegram: o servico ja entrega por e-mail
e Telegram os outros checks, com canais testados. Um bot proprio seria mais um
segredo na VM e mais um canal a manter. Decisao do dono em 05/11/2026 (issue #4).

Como o check e usado: o vigia pinga sucesso quando esta tudo bem e manda
`/fail` com o motivo no corpo quando nao esta. O corpo aparece no painel e na
notificacao. Um so processo fala com o check (o vigia): se o coletor tambem
falasse, um "ok" do vigia apagaria o "401" que o coletor acabou de mandar.

Regra: falha ao alertar nunca derruba quem alerta. O alerta e acessorio.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("coletor")


class Healthchecks:
    def __init__(self, url: str | None, sessao: requests.Session | None = None):
        self.url = url.rstrip("/") if url else None
        self.sessao = sessao or requests.Session()

    @property
    def configurado(self) -> bool:
        return bool(self.url)

    def ok(self, texto: str = "") -> bool:
        return self._pingar("", texto)

    def falha(self, texto: str) -> bool:
        return self._pingar("/fail", texto)

    def _pingar(self, sufixo: str, texto: str) -> bool:
        if not self.configurado:
            # Ping ok sem texto (toda rodada boa) nao enche o log de aviso.
            if texto:
                log.warning("alerta_nao_configurado", extra={"campos": {"texto": texto}})
            return False
        try:
            r = self.sessao.post(self.url + sufixo, data=texto.encode("utf-8"), timeout=10)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            # Nao loga a URL: quem tem a URL de ping consegue mexer no check.
            log.error("alerta_falhou", extra={"campos": {"erro": type(e).__name__, "texto": texto}})
            return False
