-- A media entre paradas preserva a decomposicao, e a espera nunca fica abaixo da
-- regular: irregularidade so pode piorar a espera.
select *
from {{ ref('fct_servico_linha_faixa') }}
where abs(espera_estimada_min - espera_regular_min - espera_excesso_min) > 0.000001
   or espera_estimada_min < espera_regular_min - 0.000001
