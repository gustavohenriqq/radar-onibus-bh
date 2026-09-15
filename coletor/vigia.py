"""Vigia: alerta se o coletor ficar mais de N minutos sem gravar arquivo novo.

Uso: python -m coletor.vigia   (roda uma vez e sai; o systemd timer repete)

Por que um processo separado e nao uma checagem dentro do coletor: se o
coletor travar, entrar em loop de crash ou o systemd desistir de reinicia-lo,
uma checagem interna morre junto com ele. O vigia mede o resultado que importa
(arquivo novo no disco), nao se o processo parece vivo.

Limite conhecido: o vigia roda na mesma VM. Se a VM inteira cair ou for
recuperada pela Oracle, ele cai junto. Para isso existe o HEALTHCHECK_URL
(servico externo que alerta quando os pings param).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from coletor import registro
from coletor.alerta import Telegram
from coletor.armazenamento import mtime_mais_recente
from coletor.config import Config

log = logging.getLogger("coletor")
LEMBRETE_S = 3600


def _ler_estado(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar_estado(caminho: Path, estado: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado), encoding="utf-8")


def verificar(cfg: Config, canal: Telegram, agora: float | None = None) -> bool:
    """Devolve True se esta tudo bem. O estado em disco evita repetir o mesmo
    alerta a cada 5 min: um alerta, um lembrete por hora, um aviso de volta."""
    agora = time.time() if agora is None else agora
    caminho_estado = cfg.dir_estado / "vigia.json"
    estado = _ler_estado(caminho_estado)
    limite_s = cfg.alerta_sem_arquivo_min * 60

    ultimo = mtime_mais_recente(cfg.dir_bronze, datetime.fromtimestamp(agora, timezone.utc))
    atraso_s = None if ultimo is None else agora - ultimo
    ok = atraso_s is not None and atraso_s <= limite_s
    log.info("vigia", extra={"campos": {"ok": ok, "atraso_s": None if atraso_s is None else round(atraso_s)}})

    if ok:
        if estado.get("em_alerta"):
            canal.enviar("[coletor-onibus] Coleta voltou: arquivo novo gravado.")
            _gravar_estado(caminho_estado, {"em_alerta": False})
        return True

    if not estado.get("em_alerta") or agora - estado.get("ultimo_aviso", 0) >= LEMBRETE_S:
        detalhe = "nenhum arquivo nas ultimas 2 horas" if atraso_s is None else f"ultimo arquivo ha {round(atraso_s / 60)} min"
        canal.enviar(f"[coletor-onibus] Sem arquivo novo ha mais de {cfg.alerta_sem_arquivo_min} min ({detalhe}). Dado desse periodo esta sendo perdido.")
        _gravar_estado(caminho_estado, {"em_alerta": True, "ultimo_aviso": agora})
    return False


def main() -> int:
    cfg = Config.do_ambiente()
    registro.configurar(cfg.dir_log, "vigia.jsonl")
    # Codigo de saida 1 quando atrasado: aparece como falha no systemctl status.
    return 0 if verificar(cfg, Telegram(cfg.telegram_token, cfg.telegram_chat_id)) else 1


if __name__ == "__main__":
    sys.exit(main())
