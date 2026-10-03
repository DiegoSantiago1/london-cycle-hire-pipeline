{# Testes genéricos próprios (sem pacote externo: menos dependência). Cada um devolve
   as linhas que violam a regra; zero linhas = passou. #}

{% test expressao_verdadeira(model, expressao) %}
    select * from {{ model }} where not ({{ expressao }})
{% endtest %}

{% test unique_combinacao(model, colunas) %}
    select {{ colunas | join(', ') }}, count(*) as repeticoes
    from {{ model }}
    group by {{ colunas | join(', ') }}
    having count(*) > 1
{% endtest %}

{% test corresponde_regex(model, column_name, regex) %}
    select * from {{ model }}
    where {{ column_name }} is not null and {{ column_name }} !~ '{{ regex }}'
{% endtest %}
