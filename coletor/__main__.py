"""Ponto de entrada: python -m coletor"""

from __future__ import annotations

import signal

from coletor import registro
from coletor.coletor import Coletor
from coletor.config import Config


def main() -> None:
    cfg = Config.do_ambiente()
    registro.configurar(cfg.dir_log, "coletas.jsonl")
    coletor = Coletor(cfg)

    # SIGTERM e o que o systemd manda no stop/restart. Em vez de morrer no meio
    # de uma escrita, o loop termina a coleta atual e sai limpo.
    def encerrar(signum, frame):
        coletor.parar.set()

    signal.signal(signal.SIGTERM, encerrar)
    signal.signal(signal.SIGINT, encerrar)
    coletor.executar()


if __name__ == "__main__":
    main()
