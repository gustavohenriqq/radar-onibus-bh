-- Qual parada corresponde a cada posicao da sequencia, por letreiro.
-- Cerca de 20% das trocas de parada pulam paradas: o feed nao diz quais foram,
-- entao o mapa e aprendido de quem as informou. A parada mais vista ganha;
-- empate cai no menor stop_id, para o resultado ser deterministico.
--
-- Sempre sobre o historico inteiro, qualquer que seja a janela.
{{ config(materialized='table') }}

with contagem as (
    select route_id, direction_id, letreiro, stop_sequence, stop_id, sum(observacoes) as observacoes
    from {{ ref('int_mapa_contagem') }}
    group by route_id, direction_id, letreiro, stop_sequence, stop_id
),

ordenado as (
    select
        *,
        row_number() over (
            partition by route_id, direction_id, letreiro, stop_sequence
            order by observacoes desc, stop_id
        ) as posicao,
        sum(observacoes) over (
            partition by route_id, direction_id, letreiro, stop_sequence
        ) as total
    from contagem
)

select
    route_id, direction_id, letreiro, stop_sequence, stop_id,
    observacoes,
    observacoes / total as participacao
from ordenado
where posicao = 1
