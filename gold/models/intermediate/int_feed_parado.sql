-- Registro das quedas do feed, uma linha por periodo, no dia em que o feed voltou.
{{ config(partition_by=['data_bh']) }}

select inicio_unix, fim_unix, duracao_s, data_bh
from {{ ref('int_feed_parado_contexto') }}
where {{ na_janela() }}
