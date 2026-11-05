-- Dado sujo conhecido: 3 linhas em 25/10/2026, uma em latitude 31,4.
-- A Silver mantem e stg_posicoes filtra. Aviso, para um numero novo aparecer.
{{ config(severity='warn', warn_if='>3') }}

select vehicle_id, vehicle_ts, latitude, longitude
from {{ source('silver', 'posicoes') }}
where data_bh between date'{{ var("data_inicio") }}' and date'{{ var("data_fim") }}'
  and not (latitude between -20.6 and -19.4 and longitude between -44.6 and -43.4)
