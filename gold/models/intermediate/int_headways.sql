-- Intervalo entre passagens consecutivas de onibus da mesma linha, no mesmo
-- sentido, na mesma parada. Vale qualquer letreiro: para quem espera no ponto,
-- variante da mesma linha e o mesmo onibus.
--
-- O headway pertence a passagem que o encerra (a data e a hora dela).
{{ config(partition_by=['data_bh']) }}

with validas as (
    select * from {{ ref('int_passagens') }} where motivo_exclusao is null
),

com_anterior as (
    select
        *,
        lag(vehicle_id) over janela as onibus_anterior,
        lag(passagem_unix) over janela as unix_anterior_parada
    from validas
    window janela as (
        partition by route_id, direction_id, stop_id
        order by passagem_unix, viagem_id, stop_sequence
    )
),

-- O mesmo onibus nao passa duas vezes no mesmo ponto em poucos minutos: e o feed
-- reatribuindo a viagem. Fica a primeira passagem.
sem_repeticao as (
    select * from com_anterior
    where not coalesce(
        vehicle_id = onibus_anterior
        and passagem_unix - unix_anterior_parada < {{ var('repeticao_mesmo_onibus_s') }},
        false
    )
),

com_headway as (
    select
        route_id, direction_id, stop_id, viagem_id, stop_sequence, vehicle_id,
        data_bh, hora_bh, passagem_unix, paradas_no_intervalo,
        passagem_unix - lag(passagem_unix) over janela as headway_s,
        lag(vehicle_id) over janela as onibus_anterior
    from sem_repeticao
    window janela as (
        partition by route_id, direction_id, stop_id
        order by passagem_unix, viagem_id, stop_sequence
    )
),

janelas as (
    select collect_list(named_struct('inicio', inicio_unix, 'fim', fim_unix)) as lista
    from {{ ref('int_feed_parado') }}
),

marcados as (
    select
        h.*,
        -- Array em vez de join: um headway longo pode cruzar mais de um periodo, e
        -- o join repetiria a linha.
        exists(j.lista, x -> h.passagem_unix > x.inicio and h.passagem_unix - h.headway_s < x.fim)
            as atravessa_feed_parado
    from com_headway h
    cross join janelas j
    where h.headway_s is not null
)

select
    *,
    headway_s <= {{ var('headway_max_min') }} * 60 and not atravessa_feed_parado as headway_valido
from marcados
