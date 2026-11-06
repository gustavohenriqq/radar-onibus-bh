{#
  Janela de processamento da Gold.

  data_inicio e data_fim dizem quais dias sao GRAVADOS. Cada modelo incremental
  devolve so esses dias, e o insert_overwrite troca so essas particoes de data_bh.

  Para calcular esses dias certo, a leitura da Silver vai alem da janela
  (contexto): viagem e headway atravessam a meia-noite. Medido no historico de
  15/09 a 04/11/2026: a viagem mais longa dura 3 h, e nenhuma ocupa mais de 2 dias.
#}

{% macro na_janela(coluna='data_bh') -%}
    {{ coluna }} between date'{{ var("data_inicio") }}' and date'{{ var("data_fim") }}'
{%- endmacro %}

{% macro contexto_inicio() -%}
    greatest(date'{{ var("data_minima") }}', date_sub(date'{{ var("data_inicio") }}', {{ var("contexto_antes_dias") }}))
{%- endmacro %}

{% macro contexto_fim() -%}
    date_add(date'{{ var("data_fim") }}', 1)
{%- endmacro %}

{% macro validar_janela() %}
    {% if execute %}
        {% set inicio = var('data_inicio') | string %}
        {% set fim = var('data_fim') | string %}
        {% set minima = var('data_minima') | string %}
        {% if inicio < minima %}
            {% do exceptions.raise_compiler_error('data_inicio ' ~ inicio ~ ' antes de data_minima ' ~ minima) %}
        {% endif %}
        {% if fim < inicio %}
            {% do exceptions.raise_compiler_error('data_fim ' ~ fim ~ ' antes de data_inicio ' ~ inicio) %}
        {% endif %}
        {# Full refresh recria a tabela com o que a consulta devolve: com uma janela
           parcial, o historico fora dela seria apagado. #}
        {% if flags.FULL_REFRESH and (inicio != minima or fim != '2099-12-31') %}
            {% do exceptions.raise_compiler_error('--full-refresh so com a janela inteira (sem --vars de data)') %}
        {% endif %}
    {% endif %}
    select 1
{% endmacro %}

{# Mesma macro do dbt, com uma marca a mais: where "janela" vira o filtro da janela. #}
{% macro get_where_subquery(relation) -%}
    {% set where = config.get('where', '') %}
    {% if where == 'janela' %}
        {% set where = na_janela() %}
    {% endif %}
    {% if where %}
        {%- set filtrado -%}
            (select * from {{ relation }} where {{ where }}) dbt_subquery
        {%- endset -%}
        {% do return(filtrado) %}
    {%- else -%}
        {% do return(relation) %}
    {%- endif -%}
{%- endmacro %}
