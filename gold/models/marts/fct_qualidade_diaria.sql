-- O que entrou e o que ficou de fora do calculo, por dia.
{{ config(partition_by=['data_bh']) }}

with passagens as (
    select
        data_bh,
        count(*) as passagens,
        sum(case when motivo_exclusao is null then 1 else 0 end) as passagens_validas,
        sum(case when motivo_exclusao = 'intervalo_longo' then 1 else 0 end) as descartadas_intervalo_longo,
        sum(case when motivo_exclusao = 'sem_mapa' then 1 else 0 end) as descartadas_sem_mapa,
        sum(case when motivo_exclusao is null and parada_do_mapa then 1 else 0 end) as paradas_pelo_mapa,
        sum(case when motivo_exclusao is null and paradas_no_intervalo > 1 then 1 else 0 end) as instantes_divididos
    from {{ ref('int_passagens') }}
    group by data_bh
),

headways as (
    select
        data_bh,
        count(*) as headways,
        sum(case when headway_valido then 1 else 0 end) as headways_validos,
        sum(case when not headway_valido and not atravessa_feed_parado then 1 else 0 end) as headways_longos,
        sum(case when atravessa_feed_parado then 1 else 0 end) as headways_feed_parado,
        count(distinct route_id) as linhas
    from {{ ref('int_headways') }}
    group by data_bh
)

select
    p.*,
    h.headways, h.headways_validos, h.headways_longos, h.headways_feed_parado, h.linhas,
    h.headways_validos / p.passagens as cobertura_passagens
from passagens p
join headways h on p.data_bh = h.data_bh
