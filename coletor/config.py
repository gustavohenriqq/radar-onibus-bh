"""Configuracao do coletor, lida de variaveis de ambiente (ou de um arquivo .env).

Por que variavel de ambiente e nao constante no codigo: a chave de acesso vem
na URL e pode ser rotacionada pela PBH sem aviso. Trocar a chave precisa ser
editar o .env e reiniciar o servico, sem commit e sem deploy de codigo. O token
do Telegram, que e segredo, tambem nunca entra no repositorio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

def _obrigatoria(nome: str) -> str:
    # Sem valor padrao de proposito: uma chave embutida no codigo continuaria
    # "funcionando" no deploy seguinte mesmo depois de rotacionada, e acabaria
    # publicada junto com o repositorio.
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise SystemExit(f"variavel {nome} nao definida; copie .env.example para .env e preencha")
    return valor


def _opcional(nome: str) -> str | None:
    valor = os.environ.get(nome, "").strip()
    return valor or None


@dataclass(frozen=True)
class Config:
    url: str
    dir_dados: Path
    dir_log: Path
    intervalo_s: int
    timeout_s: float
    backoff_max_s: int
    alerta_sem_arquivo_min: int
    user_agent: str
    telegram_token: str | None
    telegram_chat_id: str | None
    healthcheck_url: str | None

    @property
    def dir_bronze(self) -> Path:
        return self.dir_dados / "bronze" / "vehicle_positions"

    @property
    def dir_estado(self) -> Path:
        # Prefixo "_" porque Spark e Hive ignoram diretorios que comecam com
        # "_" ou "." ao ler um lake. Estado operacional nao e dado.
        return self.dir_dados / "_estado"

    @classmethod
    def do_ambiente(cls) -> Config:
        # Nao sobrescreve o que ja esta no ambiente: no systemd, o
        # EnvironmentFile tem prioridade sobre o .env.
        load_dotenv(override=False)
        contato = os.environ.get("COLETOR_CONTATO", "https://github.com/gustavohenriqq")
        return cls(
            url=_obrigatoria("COLETOR_URL"),
            dir_dados=Path(os.environ.get("COLETOR_DIR_DADOS", "./dados")),
            dir_log=Path(os.environ.get("COLETOR_DIR_LOG", "./logs")),
            intervalo_s=int(os.environ.get("COLETOR_INTERVALO_S", "30")),
            timeout_s=float(os.environ.get("COLETOR_TIMEOUT_S", "15")),
            backoff_max_s=int(os.environ.get("COLETOR_BACKOFF_MAX_S", "300")),
            alerta_sem_arquivo_min=int(os.environ.get("COLETOR_ALERTA_SEM_ARQUIVO_MIN", "10")),
            # User-Agent honesto: quem opera o feed consegue identificar o
            # coletor e saber com quem falar se ele atrapalhar.
            user_agent=f"coletor-onibus-bh/0.1 (+{contato})",
            telegram_token=_opcional("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_opcional("TELEGRAM_CHAT_ID"),
            healthcheck_url=_opcional("HEALTHCHECK_URL"),
        )
