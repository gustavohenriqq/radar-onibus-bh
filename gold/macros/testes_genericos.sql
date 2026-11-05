{# Testes proprios, sem pacote externo: rodam sem acesso ao hub do dbt. #}

{% test combinacao_unica(model, colunas) %}
select {{ colunas | join(', ') }}, count(*) as repeticoes
from {{ model }}
group by {{ colunas | join(', ') }}
having count(*) > 1
{% endtest %}

{% test entre(model, column_name, minimo, maximo) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} < {{ minimo }} or {{ column_name }} > {{ maximo }}
{% endtest %}
