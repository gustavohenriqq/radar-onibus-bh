"""Job horario: copia os conteineres horarios para o bucket de backup.

Uso: python -m backup.enviar [--limite N]

Por que existe: os originais por coleta sao apagados 48 h depois de
compactados, entao os conteineres em /dados/bronze_horario sao a unica copia do
historico. Se o volume falhar, tudo desde 14/09/2026 some, e posicao de onibus
que nao foi gravada nao volta.

Garantias:

- So conta como feito o que foi lido de volta do bucket e bateu o SHA-256 do
  manifesto. Status 200 no envio nao prova nada sobre o que ficou gravado.
- Idempotente. O estado local guarda o que ja foi conferido; rodar de novo nao
  reenvia. Se o estado se perder, o job tenta de novo, o bucket recusa a
  sobrescrita (regra de retencao), e o job confere o que ja esta la.
- Backfill por construcao: varre todos os manifestos, nao so os de ontem.
- Conteiner que mudou depois de ter ido para o backup vira falha, nunca
  sobrescrita silenciosa.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from coletor import registro
from coletor.config import Config
from compactacao import formato
from compactacao.compactar import ping
from compactacao.horas import Hora, conteiner_valido
from backup.remoto import NaoEncontrado, Remoto

log = logging.getLogger("coletor")


def nome_objeto(caminho: Path, cfg: Config) -> str:
    # O nome no bucket espelha o caminho dentro de /dados, entao restaurar e
    # baixar para o mesmo lugar, sem tabela de traducao.
    return caminho.relative_to(cfg.dir_dados).as_posix()


def horas_compactadas(cfg: Config) -> list[Hora]:
    horas = []
    for m in sorted(cfg.dir_bronze_horario.glob("dt=*/vp_*.pb.json")):
        dt = m.parent.name[3:]
        hh = m.name.split("T")[1][:2]
        horas.append(Hora(dt, hh))
    return horas


def ler_estado(caminho: Path) -> dict[str, str]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_estado(caminho: Path, estado: dict[str, str]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.tmp")
    temporario.write_text(json.dumps(estado, indent=0, sort_keys=True), encoding="utf-8")
    temporario.replace(caminho)


def garantir_objeto(remoto: Remoto, nome: str, caminho: Path, sha_esperado: str) -> str:
    """Envia se preciso e confere lendo de volta. Devolve 'enviado' ou 'ja_existia'."""
    status = remoto.enviar(nome, caminho)
    situacao = "enviado" if 200 <= status < 300 else "ja_existia"
    try:
        sha_remoto = remoto.sha256(nome)
    except NaoEncontrado:
        raise RuntimeError(f"{nome}: envio respondeu http {status} e o objeto nao existe no bucket")
    if sha_remoto != sha_esperado:
        # Com a regra de retencao, um objeto divergente nao pode ser trocado.
        # Precisa de gente olhando, nao de nova tentativa.
        raise RuntimeError(f"{nome}: sha256 no bucket difere do local (http {status} no envio)")
    return situacao


def enviar_hora(hora: Hora, cfg: Config, remoto: Remoto, estado: dict[str, str]) -> dict | None:
    conteiner = hora.conteiner(cfg.dir_bronze_horario)
    manifesto = hora.manifesto(cfg.dir_bronze_horario)
    sha_conteiner = json.loads(manifesto.read_text(encoding="utf-8"))["sha256_conteiner"]
    sha_manifesto = formato.sha256_arquivo(manifesto)
    n_conteiner, n_manifesto = nome_objeto(conteiner, cfg), nome_objeto(manifesto, cfg)

    if estado.get(n_conteiner) == sha_conteiner and estado.get(n_manifesto) == sha_manifesto:
        return None
    if n_conteiner in estado and estado[n_conteiner] != sha_conteiner:
        raise RuntimeError(f"{n_conteiner} mudou depois de ir para o backup")

    t0 = time.perf_counter()
    # Conteiner antes do manifesto: um manifesto no bucket sempre aponta para
    # um conteiner que ja esta la.
    s1 = garantir_objeto(remoto, n_conteiner, conteiner, sha_conteiner)
    s2 = garantir_objeto(remoto, n_manifesto, manifesto, sha_manifesto)
    estado[n_conteiner], estado[n_manifesto] = sha_conteiner, sha_manifesto
    return {
        "hora": f"{hora.dt} {hora.hh}h",
        "conteiner": s1,
        "manifesto": s2,
        "mb": round(conteiner.stat().st_size / 1048576, 2),
        "segundos": round(time.perf_counter() - t0, 1),
    }


def executar(cfg: Config, remoto: Remoto, agora: datetime, limite: int | None = None) -> tuple[int, int, int]:
    """Devolve (horas enviadas, horas ja em dia, falhas)."""
    caminho_estado = cfg.dir_estado / "backup.json"
    estado = ler_estado(caminho_estado)
    corte = agora - timedelta(hours=cfg.backup_folga_h)

    enviadas = em_dia = falhas = 0
    for hora in horas_compactadas(cfg):
        if hora.fim > corte:
            continue  # hora recente: a compactacao ainda pode refazer o conteiner
        if limite is not None and enviadas >= limite:
            break
        ok, motivo = conteiner_valido(hora, cfg.dir_bronze_horario, cfg.dir_bronze)
        if not ok:
            falhas += 1
            log.error("conteiner_invalido", extra={"campos": {"hora": f"{hora.dt} {hora.hh}", "motivo": motivo}})
            continue
        try:
            resumo = enviar_hora(hora, cfg, remoto, estado)
        except Exception as e:
            falhas += 1
            log.exception("falha", extra={"campos": {"hora": f"{hora.dt} {hora.hh}", "erro": str(e)[:200]}})
            continue
        if resumo is None:
            em_dia += 1
        else:
            enviadas += 1
            log.info("enviada", extra={"campos": resumo})
            # Grava a cada hora: se o job cair no meio de um backfill longo, o
            # que ja foi conferido nao e refeito.
            gravar_estado(caminho_estado, estado)
    return enviadas, em_dia, falhas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Copia os conteineres horarios para o bucket de backup")
    p.add_argument("--limite", type=int, default=None, help="maximo de horas enviadas nesta execucao")
    args = p.parse_args(argv)

    cfg = Config.do_ambiente(exigir_url=False)
    registro.configurar(cfg.dir_log, "backup.jsonl")
    if not cfg.backup_par_url:
        log.error("sem_destino", extra={"campos": {"erro": "BACKUP_PAR_URL nao definida"}})
        ping(cfg.healthcheck_backup_url, "/fail")
        return 1

    enviadas, em_dia, falhas = executar(cfg, Remoto(cfg.backup_par_url), datetime.now(timezone.utc), args.limite)
    log.info("fim", extra={"campos": {"enviadas": enviadas, "ja_em_dia": em_dia, "falhas": falhas}})
    ping(cfg.healthcheck_backup_url, "" if falhas == 0 else "/fail")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
