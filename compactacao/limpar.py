"""Apaga os arquivos por coleta cuja hora ja esta compactada e conferida.

Uso: python -m compactacao.limpar [--quarentena-h N] [--seco]

Por que e um job separado da compactacao: apagar dado insubstituivel e a acao
mais perigosa deste projeto. Ela nao pode ser efeito colateral de um job que
roda toda hora. Separado, da para rodar a compactacao por dias sem apagar nada
e so depois ligar este.

Duas travas, nesta ordem:

1. Quarentena. So entra hora cujo conteiner tem mais de N horas (48 por
   padrao). Custa ~240 MB de disco e e o seguro contra um bug que so aparece
   no dia seguinte.
2. Conferencia no momento de apagar. Reconstroi cada coleta a partir do
   conteiner e compara o SHA-256 com o arquivo original que ainda esta no
   disco. So apaga o que bateu. Verificacao feita ontem nao vale: o que
   protege e conferir agora, no mesmo processo que apaga.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from coletor import registro
from coletor.config import Config
from compactacao import formato
from compactacao.compactar import ping
from compactacao.horas import Hora, conteiner_valido, horas_com_dado

log = logging.getLogger("coletor")


def limpar_hora(hora: Hora, cfg: Config, seco: bool) -> dict:
    """Confere e apaga os originais de uma hora. Devolve o resumo do que fez."""
    dir_origem = hora.dir_origem(cfg.dir_bronze)
    manifesto = json.loads(hora.manifesto(cfg.dir_bronze_horario).read_text(encoding="utf-8"))
    esperados: dict[str, str] = manifesto["sha256_originais"]

    confere: dict[str, str] = {}
    for nome, protobuf in formato.ler(hora.conteiner(cfg.dir_bronze_horario)):
        confere[f"{nome}.pb.gz"] = hashlib.sha256(formato.reconstruir_gz(protobuf)).hexdigest()
    if confere != esperados:
        raise RuntimeError(
            f"conteiner nao reproduz o manifesto: {len(confere)} coletas no conteiner, {len(esperados)} no manifesto"
        )

    # Duas passadas, e nao uma. Apagar enquanto confere deixaria meia hora
    # apagada quando o arquivo divergente aparece no meio da lista, e o que
    # sobra nao e recuperavel. Primeiro confere tudo, depois apaga tudo.
    presentes = sorted(dir_origem.glob("*.pb.gz"))
    for arquivo in presentes:
        esperado = esperados.get(arquivo.name)
        if esperado is None:
            # Arquivo que nao esta no conteiner: nunca apagar. Ou o conteiner
            # esta desatualizado, ou apareceu coleta depois. A proxima execucao
            # da compactacao resolve, porque a contagem nao bate mais.
            raise RuntimeError(f"arquivo fora do conteiner: {arquivo.name}")
        if formato.sha256_arquivo(arquivo) != esperado:
            raise RuntimeError(f"hash diferente do manifesto: {arquivo.name}")

    apagados = bytes_liberados = 0
    for arquivo in presentes:
        bytes_liberados += arquivo.stat().st_size
        if not seco:
            arquivo.unlink()
        apagados += 1

    if not seco and not any(dir_origem.iterdir()):
        dir_origem.rmdir()
    return {
        "hora": f"{hora.dt} {hora.hh}h",
        "conferidas": len(confere),
        "apagados": apagados,
        "mb_liberados": round(bytes_liberados / 1048576, 2),
        "seco": seco,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Apaga originais de horas ja compactadas e conferidas")
    p.add_argument("--quarentena-h", type=int, default=None, help="idade minima do conteiner, em horas")
    p.add_argument("--seco", action="store_true", help="confere e mostra o que apagaria, sem apagar")
    args = p.parse_args(argv)

    cfg = Config.do_ambiente(exigir_url=False)
    registro.configurar(cfg.dir_log, "limpeza.jsonl")
    quarentena = cfg.compactacao_quarentena_h if args.quarentena_h is None else args.quarentena_h
    agora = datetime.now(timezone.utc)
    limite = agora - timedelta(hours=quarentena)

    fila = []
    for hora in horas_com_dado(cfg.dir_bronze):
        if hora.fim > limite:
            continue  # ainda em quarentena
        ok, motivo = conteiner_valido(hora, cfg.dir_bronze_horario, cfg.dir_bronze)
        if ok:
            fila.append(hora)
        else:
            log.warning("pulada", extra={"campos": {"hora": f"{hora.dt} {hora.hh}", "motivo": motivo}})
    log.info("inicio", extra={"campos": {"horas_elegiveis": len(fila), "quarentena_h": quarentena, "seco": args.seco}})

    falhas = 0
    for hora in fila:
        try:
            log.info("limpa", extra={"campos": limpar_hora(hora, cfg, args.seco)})
        except Exception as e:
            falhas += 1
            log.exception("falha", extra={"campos": {"hora": f"{hora.dt} {hora.hh}", "erro": str(e)[:200]}})

    log.info("fim", extra={"campos": {"horas": len(fila), "falhas": falhas}})
    if falhas:
        ping(cfg.healthcheck_compactacao_url, "/fail")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
