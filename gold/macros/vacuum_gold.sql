{#
  VACUUM de todas as tabelas Delta da Gold. Uso: dbt run-operation vacuum_gold

  Cada insert_overwrite deixa os arquivos que substituiu no disco, por causa do
  historico de versoes do Delta. Com a DAG horaria regravando dois dias a cada
  hora, sem isto a pasta cresceria sem parar: com 7 dias de retencao, o disco
  chegou a 97% em 15/11/2026. 24 h guardam um dia de time travel.

  O Delta 4.4 ignora o RETAIN n HOURS e usa a propriedade
  delta.deletedFileRetentionDuration, entao ela e gravada antes de cada VACUUM.
#}
{% macro vacuum_gold(horas=24) %}
    {% for node in graph.nodes.values()
          if node.resource_type in ['model', 'seed']
          and node.config.materialized in ['table', 'incremental', 'seed'] %}
        {% set relacao = adapter.get_relation(database=node.database, schema=node.schema, identifier=node.alias) %}
        {% if relacao %}
            {% do run_query("ALTER TABLE " ~ relacao ~ " SET TBLPROPERTIES ('delta.deletedFileRetentionDuration' = 'interval " ~ horas ~ " hours')") %}
            {% do run_query('VACUUM ' ~ relacao) %}
            {% do log('vacuum ' ~ relacao, info=true) %}
        {% endif %}
    {% endfor %}
{% endmacro %}
