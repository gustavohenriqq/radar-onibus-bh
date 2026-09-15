"""Log estruturado em JSON Lines, com rotacao.

Por que JSON Lines e nao texto livre: o log de coletas e dado operacional que
vai ser lido por maquina depois (taxa de sucesso, latencia, repeticoes por
hora). Uma linha JSON por evento se le com pandas ou Spark sem regex.

Por que rotacao: cada coleta gera uma linha de ~300 bytes, perto de 1 MB por
dia. Sem rotacao, o proprio log acaba competindo com o dado por disco.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        linha = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "evento": record.getMessage(),
        }
        linha.update(getattr(record, "campos", {}))
        if record.exc_info:
            linha["traceback"] = self.formatException(record.exc_info)
        return json.dumps(linha, ensure_ascii=False)


def configurar(dir_log: Path, nome_arquivo: str) -> logging.Logger:
    dir_log.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("coletor")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    formato = FormatoJson()

    # 10 MB x 10 arquivos: cerca de 100 dias de historico com teto fixo de disco.
    arquivo = RotatingFileHandler(dir_log / nome_arquivo, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
    arquivo.setFormatter(formato)
    log.addHandler(arquivo)

    # stdout vai para o journald no systemd, que tem teto de tamanho proprio.
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(formato)
    log.addHandler(tela)
    return log
