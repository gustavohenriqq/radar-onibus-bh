"""Protobuf GTFS-RT cru -> linhas tipadas. Python puro, sem Spark.

Separado do job para ser testado sozinho: e aqui que um bug de parsing
estragaria a Silver inteira, e o Bronze cru existe justamente para que esse bug
possa ser corrigido e reprocessado.

Uma linha por entidade `vehicle` do feed. Campo ausente vira None, nunca zero:
`speed` ausente e "nao informado", e zero e "parado". Confundir os dois quebra
qualquer calculo de velocidade na fase seguinte.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from google.transit import gtfs_realtime_pb2 as gtfs

# Ordem e nomes iguais ao schema Spark em silver/processar.py
COLUNAS = (
    "coleta_ts", "feed_ts", "entity_id", "vehicle_id", "vehicle_label", "vehicle_ts",
    "trip_id", "route_id", "direction_id", "start_date", "start_time",
    "latitude", "longitude", "bearing", "speed",
    "current_stop_sequence", "current_status", "stop_id",
)


def instante_da_coleta(nome: str) -> datetime:
    """'20260915T100000Z' -> datetime UTC. E o horario real da coleta."""
    return datetime.strptime(nome, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _ts(segundos: int) -> datetime | None:
    return datetime.fromtimestamp(segundos, timezone.utc) if segundos else None


def decodificar(nome_coleta: str, protobuf: bytes) -> Iterator[tuple]:
    feed = gtfs.FeedMessage()
    feed.ParseFromString(protobuf)
    coleta = instante_da_coleta(nome_coleta)
    feed_ts = _ts(feed.header.timestamp)
    for e in feed.entity:
        if not e.HasField("vehicle"):
            continue
        v = e.vehicle
        trip, pos = v.trip, v.position
        tem_trip, tem_pos = v.HasField("trip"), v.HasField("position")
        yield (
            coleta,
            feed_ts,
            e.id or None,
            v.vehicle.id or None,
            v.vehicle.label or None,
            _ts(v.timestamp),
            (trip.trip_id or None) if tem_trip else None,
            (trip.route_id or None) if tem_trip else None,
            trip.direction_id if tem_trip and trip.HasField("direction_id") else None,
            (trip.start_date or None) if tem_trip else None,
            (trip.start_time or None) if tem_trip else None,
            pos.latitude if tem_pos else None,
            pos.longitude if tem_pos else None,
            pos.bearing if tem_pos and pos.HasField("bearing") else None,
            pos.speed if tem_pos and pos.HasField("speed") else None,
            v.current_stop_sequence if v.HasField("current_stop_sequence") else None,
            v.current_status if v.HasField("current_status") else None,
            v.stop_id or None,
        )


def taxa_de_duplicacao(linhas) -> tuple[int, int, float]:
    """(registros, chaves (vehicle_id, vehicle_ts) distintas, fracao repetida).

    Base do percentual: total de registros lidos, a mesma da auditoria de
    16/09/2026, para os numeros serem comparaveis.
    """
    i_id, i_ts = COLUNAS.index("vehicle_id"), COLUNAS.index("vehicle_ts")
    total, chaves = 0, set()
    for linha in linhas:
        total += 1
        chaves.add((linha[i_id], linha[i_ts]))
    return total, len(chaves), (1 - len(chaves) / total) if total else 0.0
