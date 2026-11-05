-- Grao fino: linha, sentido, parada, dia, faixa horaria.
--
-- Formulas, com H o headway:
--   CV                = desvio(H) / media(H), desvio populacional
--   espera estimada   = E[H^2] / (2 E[H]) = (media/2)(1 + CV^2)
--   espera regular    = media / 2, o que se esperaria com os mesmos onibus
--                       igualmente espacados
--   espera em excesso = estimada - regular: o custo da irregularidade
{{ config(partition_by=['data_bh']) }}

with base as (
    select
        h.route_id, h.direction_id, h.stop_id, h.data_bh,
        f.faixa_horaria, f.ordem_faixa,
        count(*) as headways,
        sum(h.headway_s) as soma_s,
        sum(h.headway_s * h.headway_s) as soma_quadrados
    from {{ ref('int_headways') }} h
    join {{ ref('faixa_horaria') }} f on h.hora_bh = f.hora_bh
    where h.headway_valido
    group by h.route_id, h.direction_id, h.stop_id, h.data_bh, f.faixa_horaria, f.ordem_faixa
),

momentos as (
    select
        *,
        soma_s / headways as media_s,
        soma_quadrados / headways as media_quadrados
    from base
)

select
    route_id, direction_id, stop_id, data_bh, faixa_horaria, ordem_faixa,
    headways,
    media_s / 60 as headway_medio_min,
    -- Media zero: todos os onibus do grupo informaram a passagem no mesmo instante.
    -- A linha fica, para nenhum headway sumir, mas o que divide pela media nao
    -- existe e sai nulo. O mart de linha ignora esses grupos.
    -- greatest: erro de arredondamento nao pode virar raiz de numero negativo.
    case when media_s > 0
        then sqrt(greatest(media_quadrados - media_s * media_s, 0)) / media_s
    end as cv_headway,
    case when media_s > 0
        then media_quadrados / (2 * media_s) / 60
    end as espera_estimada_min,
    media_s / 2 / 60 as espera_regular_min,
    case when media_s > 0
        then greatest(media_quadrados / (2 * media_s) - media_s / 2, 0) / 60
    end as espera_excesso_min
from momentos
