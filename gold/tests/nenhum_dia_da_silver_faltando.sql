-- Todo dia que existe na Silver dentro da janela tem que chegar ao mart.
with silver as (
    select distinct data_bh from {{ ref('stg_posicoes') }}
),

mart as (
    select distinct data_bh from {{ ref('fct_servico_linha_faixa') }}
)

select s.data_bh
from silver s
left join mart m on s.data_bh = m.data_bh
where m.data_bh is null
