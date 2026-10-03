{#
  Viagens tipadas e padronizadas (dois vocabulários da TfL nas mesmas colunas).
  Tabela, e não view: são 41 milhões de linhas e os agregados leem daqui várias vezes.
  Cada coluna derivada é calculada uma vez (CTE "derivadas") e reaproveitada.

  Regras medidas em 03/10/2026 (docs/DECISOES.md D31-D35):
  - data: 'AAAA-MM-DD HH:MI' ou 'DD/MM/AAAA HH:MI[:SS]' (os 4 arquivos que passaram pelo
    Excel), horário de Londres sem fuso -> timestamptz;
  - hora repetida no fim do horário de verão: o PostgreSQL usa a segunda ocorrência (GMT);
    essas viagens ficam marcadas em hora_ambigua;
  - duração: da coluna de duração (ms no formato novo, s no antigo), nunca de fim - início;
  - estação (formato novo): número com até 6 dígitos completado com zeros à esquerda
    (o Excel tirou os zeros em 4 arquivos) = TerminalName da API. Códigos com sufixo
    ('...444', '-1', 'old2', nome '_OLD') são o local antigo de estações que mudaram de
    lugar: terminal fica nulo e local_antigo = true.
#}
{{ config(materialized='table', tags=['viagens'], indexes=[
    {'columns': ['inicio_local']},
]) }}

with fonte as (
    select v.*, a.vocabulario
    from {{ source('bruto', 'viagens') }} v
    join {{ source('controle', 'arquivos_viagens') }} a using (arquivo)
),

derivadas as (
    select
        *,
        {{ hora_local('inicio') }} as inicio_local,
        {{ hora_local('fim') }} as fim_local,
        {{ terminal('estacao_inicio_numero', 'estacao_inicio_nome') }} as terminal_inicio,
        {{ terminal('estacao_fim_numero', 'estacao_fim_nome') }} as terminal_fim
    from fonte
)

select
    numero::bigint as numero,
    arquivo,
    linha,
    vocabulario as formato,
    inicio_local,
    inicio_local at time zone 'Europe/London' as inicio,
    fim_local,
    fim_local at time zone 'Europe/London' as fim,
    {{ hora_repetida('inicio_local') }} or coalesce({{ hora_repetida('fim_local') }}, false)
        as hora_ambigua,
    case
        when vocabulario = 'novo' then round(duracao_ms::bigint / 1000.0)::integer
        else duracao_s::integer
    end as duracao_s,
    estacao_inicio_numero as estacao_inicio_codigo,
    trim(estacao_inicio_nome) as estacao_inicio_nome,
    estacao_fim_numero as estacao_fim_codigo,
    trim(estacao_fim_nome) as estacao_fim_nome,
    terminal_inicio as estacao_inicio_terminal,
    terminal_fim as estacao_fim_terminal,
    vocabulario = 'novo' and terminal_inicio is null as local_antigo_inicio,
    vocabulario = 'novo' and estacao_fim_numero is not null and terminal_fim is null
        as local_antigo_fim,
    bicicleta,
    modelo
from derivadas
