"""Configuracao do coletor, lida de variaveis de ambiente (ou de um arquivo .env).

Por que variavel de ambiente e nao constante no codigo: a chave de acesso vem
na URL e pode ser rotacionada pela PBH sem aviso. Trocar a chave precisa ser
editar o .env e reiniciar o servico, sem commit e sem deploy de codigo. As URLs
de ping do healthchecks, que sao segredo, tambem nunca entram no repositorio.
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
    healthcheck_url: str | None
    healthcheck_compactacao_url: str | None
    compactacao_folga_min: int
    compactacao_quarentena_h: int
    compactacao_nivel_zstd: int
    # Com valor padrao para os testes e jobs antigos nao precisarem conhecer o
    # backup. Ficam no fim porque dataclass exige campos com padrao por ultimo.
    backup_par_url: str | None = None
    healthcheck_backup_url: str | None = None
    backup_folga_h: int = 2
    healthcheck_eventos_url: str | None = None
    alerta_feed_parado_min: int = 10

    @property
    def dir_bronze(self) -> Path:
        return self.dir_dados / "bronze" / "vehicle_positions"

    @property
    def dir_bronze_horario(self) -> Path:
        # Fica fora de dir_bronze de proposito: quem le a camada compactada nao
        # deve esbarrar nos arquivos por coleta, e vice-versa.
        return self.dir_dados / "bronze_horario" / "vehicle_positions"

    @property
    def dir_estado(self) -> Path:
        # Prefixo "_" porque Spark e Hive ignoram diretorios que comecam com
        # "_" ou "." ao ler um lake. Estado operacional nao e dado.
        return self.dir_dados / "_estado"

    @classmethod
    def do_ambiente(cls, exigir_url: bool = True) -> Config:
        """`exigir_url=False` para os jobs que so mexem em arquivo ja gravado:
        compactacao e limpeza nao falam com a API, entao nao devem morrer por
        causa de uma chave de acesso ausente."""
        # Nao sobrescreve o que ja esta no ambiente: no systemd, o
        # EnvironmentFile tem prioridade sobre o .env.
        load_dotenv(override=False)
        contato = os.environ.get("COLETOR_CONTATO", "https://github.com/gustavohenriqq")
        return cls(
            url=_obrigatoria("COLETOR_URL") if exigir_url else os.environ.get("COLETOR_URL", ""),
            dir_dados=Path(os.environ.get("COLETOR_DIR_DADOS", "./dados")),
            dir_log=Path(os.environ.get("COLETOR_DIR_LOG", "./logs")),
            intervalo_s=int(os.environ.get("COLETOR_INTERVALO_S", "30")),
            timeout_s=float(os.environ.get("COLETOR_TIMEOUT_S", "15")),
            backoff_max_s=int(os.environ.get("COLETOR_BACKOFF_MAX_S", "300")),
            alerta_sem_arquivo_min=int(os.environ.get("COLETOR_ALERTA_SEM_ARQUIVO_MIN", "10")),
            # User-Agent honesto: quem opera o feed consegue identificar o
            # coletor e saber com quem falar se ele atrapalhar.
            user_agent=f"coletor-onibus-bh/0.1 (+{contato})",
            healthcheck_url=_opcional("HEALTHCHECK_URL"),
            healthcheck_compactacao_url=_opcional("HEALTHCHECK_COMPACTACAO_URL"),
            # 20 min de folga: cobre relogio da VM fora de hora, jitter do timer
            # e uma coleta atrasada pelo backoff, que tem teto de 5 min.
            compactacao_folga_min=int(os.environ.get("COMPACTACAO_FOLGA_MIN", "20")),
            # Quarentena antes de apagar o original. 48 h custam ~240 MB de
            # disco e sao o seguro contra um bug apagar dado insubstituivel.
            compactacao_quarentena_h=int(os.environ.get("COMPACTACAO_QUARENTENA_H", "48")),
            compactacao_nivel_zstd=int(os.environ.get("COMPACTACAO_NIVEL_ZSTD", "10")),
            # URL pre-autenticada do bucket de backup. E segredo: quem tem a URL
            # le e grava no bucket (apagar ela nao permite).
            backup_par_url=_opcional("BACKUP_PAR_URL"),
            healthcheck_backup_url=_opcional("HEALTHCHECK_BACKUP_URL"),
            backup_folga_h=int(os.environ.get("BACKUP_FOLGA_H", "2")),
            # Check coletor-eventos: so o vigia pinga (coletor/alerta.py).
            healthcheck_eventos_url=_opcional("HEALTHCHECK_EVENTOS_URL"),
            # Quedas do feed com status 200 medidas na Gold: 16 de 15/09 a
            # 04/11, de ate 82 min. 10 min separa queda de onibus atrasado.
            alerta_feed_parado_min=int(os.environ.get("COLETOR_ALERTA_FEED_PARADO_MIN", "10")),
        )
