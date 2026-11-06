{#
  VACUUM de todas as tabelas Delta da Gold. Uso: dbt run-operation vacuum_gold

  Cada insert_overwrite deixa os arquivos que substituiu no disco, por causa do
  historico de versoes do Delta. Com a DAG horaria regravando dois dias a cada
  hora, sem isto a pasta cresceria sem parar. 168 h e o padrao do Delta: permite
  voltar uma semana com time travel.
#}
{% macro vacuum_gold(horas=168) %}
    {% for node in graph.nodes.values()
          if node.resource_type in ['model', 'seed']
          and node.config.materialized in ['table', 'incremental', 'seed'] %}
        {% set relacao = adapter.get_relation(database=node.database, schema=node.schema, identifier=node.alias) %}
        {% if relacao %}
            {% do run_query('VACUUM ' ~ relacao ~ ' RETAIN ' ~ horas ~ ' HOURS') %}
            {% do log('vacuum ' ~ relacao, info=true) %}
        {% endif %}
    {% endfor %}
{% endmacro %}
