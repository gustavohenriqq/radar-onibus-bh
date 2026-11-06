{#
  O dbt-spark 1.11 recarrega um seed apagando a tabela e criando de novo. Com
  location_root, a tabela aponta para uma pasta fixa: o drop tira so o registro
  no catalogo, os arquivos Delta ficam, e o insert seguinte soma uma copia nova.
  Medido em 05/11/2026: tres builds deixaram feriados com 18 linhas para 6 datas
  e duplicaram o mart de linha nos feriados.

  Aqui a tabela e sempre criada com create or replace, que no Delta troca
  conteudo e esquema na mesma pasta, exista ou nao o registro no catalogo. Como o
  Airflow roda dbt build toda hora, sem isso o seed cresceria uma copia por hora.
#}
{% macro spark__reset_csv_table(model, full_refresh, old_relation, agate_table) %}
  {{ return(create_csv_table(model, agate_table)) }}
{% endmacro %}

{% macro spark__create_csv_table(model, agate_table) %}
  {%- set column_override = model['config'].get('column_types', {}) -%}
  {%- set quote_seed_column = model['config'].get('quote_columns', None) -%}

  {% set sql %}
    create or replace table {{ this.render() }} (
        {%- for col_name in agate_table.column_names -%}
            {%- set inferred_type = adapter.convert_type(agate_table, loop.index0) -%}
            {%- set type = column_override.get(col_name, inferred_type) -%}
            {%- set column_name = (col_name | string) -%}
            {{ adapter.quote_seed_column(column_name, quote_seed_column) }} {{ type }} {%- if not loop.last -%}, {%- endif -%}
        {%- endfor -%}
    )
    {{ file_format_clause() }}
    {{ partition_cols(label="partitioned by") }}
    {{ clustered_cols(label="clustered by") }}
    {{ location_clause() }}
    {{ comment_clause() }}
  {% endset %}

  {% call statement('_') -%}
    {{ sql }}
  {%- endcall %}

  {{ return(sql) }}
{% endmacro %}
