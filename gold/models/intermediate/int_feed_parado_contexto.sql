-- Periodos em que a frota inteira nao publicou nenhuma posicao nova: o feed caiu.
--
-- Nessas horas o coletor continua recebendo status 200, com o relogio do cabecalho
-- andando, posicoes congeladas e depois lista vazia. Os onibus seguem rodando, entao
-- um headway que atravessa o periodo nao mede o servico, e sim a queda do feed.
--
-- View sobre o contexto inteiro: int_headways precisa das quedas da vespera, que
-- ficam fora da janela gravada. int_feed_parado guarda o registro por dia.
{{ config(materialized='view') }}

with instantes as (
    select distinct posicao_unix from {{ ref('stg_posicoes') }}
),

com_anterior as (
    select
        lag(posicao_unix) over (order by posicao_unix) as inicio_unix,
        posicao_unix as fim_unix
    from instantes
)

select
    inicio_unix,
    fim_unix,
    fim_unix - inicio_unix as duracao_s,
    to_date(from_utc_timestamp(timestamp_seconds(fim_unix), 'America/Sao_Paulo')) as data_bh
from com_anterior
where fim_unix - inicio_unix >= {{ var('feed_parado_s') }}
