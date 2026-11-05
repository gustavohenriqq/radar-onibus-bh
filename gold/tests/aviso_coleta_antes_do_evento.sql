-- Dado sujo conhecido: 1 linha em 27/10/2026, relogio do veiculo adiantado em 4 s.
-- Nao afeta a Gold, que usa vehicle_ts. Aviso, para um numero novo aparecer.
{{ config(severity='warn', warn_if='>1') }}

select vehicle_id, vehicle_ts, primeira_coleta_ts
from {{ source('silver', 'posicoes') }}
where data_bh between date'{{ var("data_inicio") }}' and date'{{ var("data_fim") }}'
  and primeira_coleta_ts < vehicle_ts
