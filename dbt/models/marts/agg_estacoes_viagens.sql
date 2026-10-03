{#
  Estações vistas nas viagens da janela: nome mais usado e volume em 12 meses. Serve
  para nomear estações que já saíram da API e para conferir a ligação com a API.
#}
{{ config(tags=['viagens']) }}

with janela as (
    select * from {{ ref('int_janela_viagens') }}
),

pontas as (
    select estacao_inicio_terminal as terminal, estacao_inicio_nome as nome, 1 as retirada, 0 as devolucao
    from {{ ref('stg_viagens') }}, janela
    where inicio_local >= inicio_janela and inicio_local < fim_janela
      and estacao_inicio_terminal is not null
    union all
    select estacao_fim_terminal, estacao_fim_nome, 0, 1
    from {{ ref('stg_viagens') }}, janela
    where inicio_local >= inicio_janela and inicio_local < fim_janela
      and estacao_fim_terminal is not null
),

nomes as (
    select terminal, nome, count(*) as n,
           row_number() over (partition by terminal order by count(*) desc, nome) as ordem
    from pontas
    group by 1, 2
)

select
    p.terminal,
    max(n.nome) filter (where n.ordem = 1) as nome,
    sum(p.retirada) as retiradas_12m,
    sum(p.devolucao) as devolucoes_12m
from pontas p
join nomes n on n.terminal = p.terminal and n.nome = p.nome
group by 1
