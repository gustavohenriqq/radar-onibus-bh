-- Colunas explicitas sobre a Silver, so com o que a Gold usa.
-- Filtra GPS fora da regiao de BH: a Silver mantem, a Gold nao calcula com ele.
--
-- Le a janela mais o contexto (macros/janela.sql). Quem grava filtra de volta
-- para a janela.
select
    vehicle_id,
    vehicle_ts,
    unix_seconds(vehicle_ts) as posicao_unix,
    data_bh,
    route_id,
    direction_id,
    vehicle_label as letreiro,
    trip_id,
    start_date,
    start_time,
    concat_ws('|', vehicle_id, trip_id, start_date, start_time) as viagem_id,
    current_stop_sequence as stop_sequence,
    stop_id
from {{ source('silver', 'posicoes') }}
where data_bh between {{ contexto_inicio() }} and {{ contexto_fim() }}
  and latitude between -20.6 and -19.4
  and longitude between -44.6 and -43.4
