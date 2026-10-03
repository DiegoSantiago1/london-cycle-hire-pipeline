{#
  Usa o nome do schema exatamente como configurado (staging, intermediario, marts).
  O padrão do dbt seria "<schema do profile>_staging"; aqui há um banco por ambiente,
  então o prefixo não separa nada e só deixaria os nomes mais confusos.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
