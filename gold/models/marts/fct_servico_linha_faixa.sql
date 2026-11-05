-- Grao de leitura: linha, sentido, dia, faixa horaria.
--
-- Calcula por parada e so depois faz a media, com peso igual para cada parada.
-- Somar os headways de todas as paradas antes misturaria ramais de frequencia
-- diferente e contaria essa diferenca como irregularidade. Peso igual porque nao
-- ha dado de embarque por parada: e o passageiro que chega numa parada qualquer.
{{ config(partition_by=['data_bh']) }}

with paradas as (
    select * from {{ ref('fct_headway_parada_faixa') }}
    where headways >= {{ var('min_headways_parada') }}
      and headway_medio_min > 0
),

agregado as (
    select
        route_id, direction_id, data_bh, faixa_horaria, ordem_faixa,
        count(*) as paradas,
        sum(headways) as headways,
        avg(headway_medio_min) as headway_medio_min,
        avg(cv_headway) as cv_headway,
        avg(espera_estimada_min) as espera_estimada_min,
        avg(espera_regular_min) as espera_regular_min,
        avg(espera_excesso_min) as espera_excesso_min
    from paradas
    group by route_id, direction_id, data_bh, faixa_horaria, ordem_faixa
)

select
    a.*,
    case
        when f.data is not null or dayofweek(a.data_bh) = 1 then 'domingo_feriado'
        when dayofweek(a.data_bh) = 7 then 'sabado'
        else 'dia_util'
    end as tipo_dia,
    -- Acima disso o passageiro consulta o horario em vez de chegar ao acaso, e a
    -- espera estimada deixa de valer como estimativa da espera real.
    a.headway_medio_min <= {{ var('alta_frequencia_min') }} as alta_frequencia
from agregado a
left join {{ ref('feriados') }} f on a.data_bh = f.data
