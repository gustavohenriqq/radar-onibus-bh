-- Uma linha por parada que uma viagem deixou para tras.
--
-- current_status e sempre IN_TRANSIT_TO, entao stop_id e a PROXIMA parada: a
-- sequencia subir de s para t quer dizer que as paradas s ate t-1 ficaram para
-- tras entre as duas posicoes. O instante e estimado dividindo esse intervalo
-- em partes iguais, uma por parada. Com uma parada so, e o ponto medio.
--
-- Sequencia que recua (reajuste do GPS) nao gera passagem: compara com o maximo
-- ja visto na viagem, nunca com a posicao anterior.
{{ config(partition_by=['data_bh']) }}

with posicoes as (
    select
        *,
        lag(posicao_unix) over janela as unix_anterior,
        lag(stop_sequence) over janela as sequencia_anterior,
        lag(stop_id) over janela as parada_anterior,
        max(stop_sequence) over (
            partition by viagem_id order by posicao_unix
            rows between unbounded preceding and 1 preceding
        ) as sequencia_maxima
    from {{ ref('stg_posicoes') }}
    window janela as (partition by viagem_id order by posicao_unix)
),

avancos as (
    select * from posicoes where stop_sequence > sequencia_maxima
),

explodido as (
    select
        a.viagem_id, a.vehicle_id, a.trip_id, a.start_date, a.start_time,
        a.route_id, a.direction_id, a.letreiro,
        a.unix_anterior,
        a.posicao_unix - a.unix_anterior as intervalo_s,
        a.stop_sequence - a.sequencia_maxima as paradas_no_intervalo,
        e.indice,
        e.passada as stop_sequence,
        -- A primeira parada do salto foi informada pelo proprio onibus, desde
        -- que a posicao anterior nao seja um recuo.
        case
            when e.indice = 0 and a.sequencia_anterior = a.sequencia_maxima then a.parada_anterior
        end as parada_informada
    from avancos a
    lateral view posexplode(sequence(a.sequencia_maxima, a.stop_sequence - 1)) e as indice, passada
),

calculado as (
    select
        e.viagem_id, e.vehicle_id, e.trip_id, e.start_date, e.start_time,
        e.route_id, e.direction_id, e.letreiro, e.stop_sequence,
        coalesce(e.parada_informada, m.stop_id) as stop_id,
        e.parada_informada is null as parada_do_mapa,
        e.paradas_no_intervalo,
        e.intervalo_s,
        e.unix_anterior + (e.indice + 0.5D) / e.paradas_no_intervalo * e.intervalo_s as passagem_unix,
        case
            when e.intervalo_s > {{ var('intervalo_max_s') }} then 'intervalo_longo'
            when coalesce(e.parada_informada, m.stop_id) is null then 'sem_mapa'
        end as motivo_exclusao
    from explodido e
    left join {{ ref('int_mapa_parada') }} m
        on e.route_id = m.route_id
       and e.direction_id = m.direction_id
       and e.letreiro = m.letreiro
       and e.stop_sequence = m.stop_sequence
),

horario_bh as (
    select
        *,
        from_utc_timestamp(timestamp_seconds(passagem_unix), 'America/Sao_Paulo') as passagem_bh
    from calculado
)

select
    *,
    to_date(passagem_bh) as data_bh,
    hour(passagem_bh) as hora_bh
from horario_bh
