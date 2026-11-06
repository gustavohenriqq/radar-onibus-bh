-- Quantas vezes cada parada apareceu em cada posicao da sequencia, por dia.
--
-- Guardar a contagem por dia deixa o mapa aprender com o historico inteiro sem
-- reler a Silver inteira a cada execucao: int_mapa_parada soma esta tabela.
{{ config(partition_by=['data_bh']) }}

select route_id, direction_id, letreiro, stop_sequence, stop_id, data_bh, count(*) as observacoes
from {{ ref('stg_posicoes') }}
where {{ na_janela() }}
group by route_id, direction_id, letreiro, stop_sequence, stop_id, data_bh
