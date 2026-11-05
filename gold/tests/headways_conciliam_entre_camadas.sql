-- Nenhum headway valido se perde entre as camadas, e a linha soma exatamente as
-- paradas que passaram do minimo de amostra e tem media acima de zero. Devolve o
-- dia que nao bater.
with origem as (
    select data_bh, count(*) as n
    from {{ ref('int_headways') }}
    where headway_valido
    group by data_bh
),

parada as (
    select
        data_bh,
        sum(headways) as n,
        sum(case when headways >= {{ var('min_headways_parada') }} and headway_medio_min > 0
            then headways else 0 end) as n_amostra
    from {{ ref('fct_headway_parada_faixa') }}
    group by data_bh
),

linha as (
    select data_bh, sum(headways) as n
    from {{ ref('fct_servico_linha_faixa') }}
    group by data_bh
)

select o.data_bh, o.n as origem, p.n as parada, p.n_amostra, l.n as linha
from origem o
full join parada p on o.data_bh = p.data_bh
full join linha l on coalesce(o.data_bh, p.data_bh) = l.data_bh
where o.n is null or p.n is null or l.n is null
   or o.n <> p.n
   or p.n_amostra <> l.n
