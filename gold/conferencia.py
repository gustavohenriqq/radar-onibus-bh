"""Segunda conta da Gold: refaz as metricas em Python puro e compara com o dbt.

As funcoes nao compartilham nada com os modelos SQL: leem a mesma Silver, em
outra linguagem e com outro algoritmo (laco por viagem em vez de janela). Se a
Gold errar uma regra, as duas contas deixam de bater.

Uso, no conteiner da Gold:
    python -m gold.conferencia --linhas 62 9104 4110 --de 2026-10-19 --ate 2026-10-23
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BH = ZoneInfo("America/Sao_Paulo")
INTERVALO_MAX_S = 300
FEED_PARADO_S = 300
REPETICAO_S = 300
HEADWAY_MAX_S = 180 * 60
MIN_HEADWAYS = 3

FAIXAS = {
    **{h: "madrugada" for h in range(0, 5)},
    5: "inicio_manha",
    **{h: "pico_manha" for h in range(6, 9)},
    **{h: "entre_picos" for h in range(9, 16)},
    **{h: "pico_tarde" for h in range(16, 20)},
    **{h: "noite" for h in range(20, 24)},
}


def janelas_feed_parado(instantes) -> list[tuple[int, int]]:
    """Instantes de toda a frota -> periodos sem nenhuma posicao nova."""
    ordenados = sorted(set(instantes))
    return [(a, b) for a, b in zip(ordenados, ordenados[1:]) if b - a >= FEED_PARADO_S]


def aprender_mapa(pings: list[dict]) -> dict:
    """(rota, sentido, letreiro, sequencia) -> parada mais vista; empate no menor id."""
    contagem: dict = defaultdict(Counter)
    for p in pings:
        chave = (p["route_id"], p["direction_id"], p["letreiro"], p["stop_sequence"])
        contagem[chave][p["stop_id"]] += 1
    return {k: min(c, key=lambda parada: (-c[parada], parada)) for k, c in contagem.items()}


def passagens_da_viagem(pings: list[dict], mapa: dict) -> list[dict]:
    """Pings de uma viagem -> passagens validas, com o instante estimado."""
    pings = sorted(pings, key=lambda p: p["unix"])
    saida = []
    maximo = None
    anterior = None
    for p in pings:
        if maximo is not None and p["stop_sequence"] > maximo:
            salto = p["stop_sequence"] - maximo
            intervalo = p["unix"] - anterior["unix"]
            if intervalo <= INTERVALO_MAX_S:
                for i in range(salto):
                    seq = maximo + i
                    if i == 0 and anterior["stop_sequence"] == maximo:
                        parada = anterior["stop_id"]
                    else:
                        parada = mapa.get((p["route_id"], p["direction_id"], p["letreiro"], seq))
                    if parada is None:
                        continue
                    saida.append({
                        "route_id": p["route_id"],
                        "direction_id": p["direction_id"],
                        "stop_id": parada,
                        "stop_sequence": seq,
                        "viagem_id": p["viagem_id"],
                        "vehicle_id": p["vehicle_id"],
                        "unix": anterior["unix"] + (i + 0.5) / salto * intervalo,
                    })
        maximo = p["stop_sequence"] if maximo is None else max(maximo, p["stop_sequence"])
        anterior = p
    return saida


def filtrar_repeticao(ordenadas: list[dict]) -> list[dict]:
    """Remove a passagem do mesmo onibus logo depois dele mesmo, em menos de 5 min."""
    saida = []
    for i, p in enumerate(ordenadas):
        ant = ordenadas[i - 1] if i else None
        if ant and ant["vehicle_id"] == p["vehicle_id"] and p["unix"] - ant["unix"] < REPETICAO_S:
            continue
        saida.append(p)
    return saida


def metricas_da_parada(headways_s: list[float]) -> dict:
    n = len(headways_s)
    media = sum(headways_s) / n
    quadrados = sum(h * h for h in headways_s) / n
    estimada = quadrados / (2 * media)
    return {
        "headways": n,
        "headway_medio_min": media / 60,
        "cv_headway": math.sqrt(max(quadrados - media * media, 0)) / media,
        "espera_estimada_min": estimada / 60,
        "espera_regular_min": media / 2 / 60,
        "espera_excesso_min": (estimada - media / 2) / 60,
    }


def calcular(pings: list[dict], de: str, ate: str, janelas=()) -> dict:
    """Pings da Silver -> metricas por (rota, sentido, data, faixa), como o mart de linha."""
    mapa = aprender_mapa(pings)

    por_viagem: dict = defaultdict(list)
    for p in pings:
        por_viagem[p["viagem_id"]].append(p)

    por_parada: dict = defaultdict(list)
    for viagem in por_viagem.values():
        for pas in passagens_da_viagem(viagem, mapa):
            por_parada[(pas["route_id"], pas["direction_id"], pas["stop_id"])].append(pas)

    grupos: dict = defaultdict(list)
    for (rota, sentido, parada), passagens in por_parada.items():
        ordenadas = sorted(passagens, key=lambda p: (p["unix"], p["viagem_id"], p["stop_sequence"]))
        limpas = filtrar_repeticao(ordenadas)
        for ant, atual in zip(limpas, limpas[1:]):
            h = atual["unix"] - ant["unix"]
            if h > HEADWAY_MAX_S:
                continue
            if any(atual["unix"] > ini and ant["unix"] < fim for ini, fim in janelas):
                continue
            instante = datetime.fromtimestamp(atual["unix"], timezone.utc).astimezone(BH)
            data = instante.date().isoformat()
            grupos[(rota, sentido, parada, data, FAIXAS[instante.hour])].append(h)

    por_linha: dict = defaultdict(list)
    for (rota, sentido, _parada, data, faixa), hs in grupos.items():
        if len(hs) >= MIN_HEADWAYS and sum(hs) > 0 and de <= data <= ate:
            por_linha[(rota, sentido, data, faixa)].append(metricas_da_parada(hs))

    resultado = {}
    for chave, paradas in por_linha.items():
        m = len(paradas)
        linha = {"paradas": m, "headways": sum(p["headways"] for p in paradas)}
        for campo in ("headway_medio_min", "cv_headway", "espera_estimada_min",
                      "espera_regular_min", "espera_excesso_min"):
            linha[campo] = sum(p[campo] for p in paradas) / m
        resultado[chave] = linha
    return resultado


def comparar(python: dict, dbt: dict, tolerancia: float = 1e-6) -> list[str]:
    """Lista de divergencias entre as duas contas. Vazia quando batem."""
    erros = [f"so no Python: {k}" for k in python.keys() - dbt.keys()]
    erros += [f"so no dbt: {k}" for k in dbt.keys() - python.keys()]
    for chave in python.keys() & dbt.keys():
        for campo, valor in python[chave].items():
            if abs(valor - dbt[chave][campo]) > tolerancia:
                erros.append(f"{chave} {campo}: python {valor} dbt {dbt[chave][campo]}")
    return erros


def main() -> int:
    from pyspark.sql import functions as F

    from silver.processar import sessao

    parser = argparse.ArgumentParser()
    parser.add_argument("--linhas", nargs="+", required=True)
    parser.add_argument("--de", required=True)
    parser.add_argument("--ate", required=True)
    parser.add_argument("--silver", default="/app/dados/silver/posicoes")
    parser.add_argument("--mart", default="/app/dados/gold/marts/fct_servico_linha_faixa")
    parser.add_argument("--inicio", default="2026-09-15")
    args = parser.parse_args()

    spark = sessao("6g")
    spark.sparkContext.setLogLevel("ERROR")

    # Lemos a janela inteira, nao so os dias conferidos: o mapa de paradas e o
    # primeiro headway de cada dia dependem do que veio antes.
    linhas = (
        spark.read.format("delta").load(args.silver)
        .filter(F.col("route_id").isin(args.linhas) & (F.col("data_bh") >= args.inicio))
        .filter("latitude between -20.6 and -19.4 and longitude between -44.6 and -43.4")
        .select(
            "vehicle_id", "route_id", "direction_id", "stop_id",
            F.col("vehicle_label").alias("letreiro"),
            F.col("current_stop_sequence").alias("stop_sequence"),
            F.unix_seconds("vehicle_ts").alias("unix"),
            F.concat_ws("|", "vehicle_id", "trip_id", "start_date", "start_time").alias("viagem_id"),
        )
        .toLocalIterator()
    )
    pings = [r.asDict() for r in linhas]
    # O feed parado se mede na frota inteira, nao so nas linhas conferidas.
    frota = (
        spark.read.format("delta").load(args.silver)
        .filter(F.col("data_bh") >= args.inicio)
        .filter("latitude between -20.6 and -19.4 and longitude between -44.6 and -43.4")
        .select(F.unix_seconds("vehicle_ts").alias("unix")).distinct()
        .toLocalIterator()
    )
    janelas = janelas_feed_parado(r.unix for r in frota)
    python = calcular(pings, args.de, args.ate, janelas)

    campos = ["paradas", "headways", "headway_medio_min", "cv_headway",
              "espera_estimada_min", "espera_regular_min", "espera_excesso_min"]
    dbt = {}
    filtro = F.col("route_id").isin(args.linhas) & F.col("data_bh").between(args.de, args.ate)
    for r in spark.read.format("delta").load(args.mart).filter(filtro).collect():
        chave = (r.route_id, r.direction_id, r.data_bh.isoformat(), r.faixa_horaria)
        dbt[chave] = {c: float(r[c]) for c in campos}

    erros = comparar(python, dbt)
    if not dbt:
        erros.append("o mart nao tem linhas nessa janela: nada foi conferido")
    print(json.dumps({
        "pings": len(pings),
        "janelas_feed_parado": len(janelas),
        "linhas_python": len(python),
        "linhas_dbt": len(dbt),
        "divergencias": len(erros),
        "headways_conferidos": sum(v["headways"] for v in python.values()),
    }))
    for e in erros[:20]:
        print(e)
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
