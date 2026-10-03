{#
  Funções de texto -> tipo usadas em stg_viagens. Rodam em 41 milhões de linhas, então
  evitam expressão regular (medido em 03/10/2026: com ~14 regex por linha a tabela
  crescia ~1 MB/s, mais de uma hora; com substr/translate fica em minutos).
#}

{# Texto de data da TfL -> timestamp sem fuso (horário de Londres).
   'AAAA-MM-DD HH:MI' ou 'DD/MM/AAAA HH:MI[:SS]'. Formato inesperado faz o cast falhar
   e o dbt parar: melhor que uma data errada em silêncio. #}
{% macro hora_local(coluna) -%}
    case
        when substr({{ coluna }}, 3, 1) = '/'
            then (substr({{ coluna }}, 7, 4) || '-' || substr({{ coluna }}, 4, 2) || '-'
                  || substr({{ coluna }}, 1, 2) || substr({{ coluna }}, 11))::timestamp
        else {{ coluna }}::timestamp
    end
{%- endmacro %}

{# A hora 01:00-02:00 do último domingo de outubro acontece duas vezes em Londres. #}
{% macro hora_repetida(coluna_local) -%}
    (
        extract(month from {{ coluna_local }}) = 10
        and extract(isodow from {{ coluna_local }}) = 7
        and extract(day from {{ coluna_local }}) >= 25
        and extract(hour from {{ coluna_local }}) = 1
    )
{%- endmacro %}

{# Número da estação no formato novo -> TerminalName da API (6 dígitos). Nulo para o
   formato antigo (outra numeração) e para o local antigo de estações que mudaram
   (código com sufixo como '...444', '-1', 'old2', ou nome terminado em '_OLD'). #}
{% macro terminal(coluna_numero, coluna_nome) -%}
    case
        when vocabulario = 'novo'
            and length({{ coluna_numero }}) between 1 and 6
            and translate({{ coluna_numero }}, '0123456789', '') = ''
            and upper(right(rtrim({{ coluna_nome }}), 4)) <> '_OLD'
            then lpad({{ coluna_numero }}, 6, '0')
    end
{%- endmacro %}
