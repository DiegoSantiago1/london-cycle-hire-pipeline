{#
  Demanda típica por estação, dia da semana e hora (horário de Londres): média de
  retiradas e de devoluções por hora, na janela de 12 meses. É o "quanto costuma sair
  e chegar aqui" que, multiplicado pelo tempo em que a estação ficou vazia ou cheia,
  dá a demanda perdida estimada (D17).
#}
{{ config(tags=['viagens']) }}

with janela as (
    select * from {{ ref('int_janela_viagens') }}
),

dias as (
    -- quantas segundas, terças... a janela tem (52 ou 53 de cada)
    select extract(isodow from d)::int as dia_semana, count(*) as n_dias
    from janela, generate_series(inicio_janela, fim_janela - 1, interval '1 day') as d
    group by 1
),

retiradas as (
    select
        estacao_inicio_terminal as terminal,
        extract(isodow from inicio_local)::int as dia_semana,
        extract(hour from inicio_local)::int as hora,
        count(*) as n
    from {{ ref('stg_viagens') }}, janela
    where inicio_local >= inicio_janela and inicio_local < fim_janela
      and estacao_inicio_terminal is not null
    group by 1, 2, 3
),

devolucoes as (
    select
        estacao_fim_terminal as terminal,
        extract(isodow from fim at time zone 'Europe/London')::int as dia_semana,
        extract(hour from fim at time zone 'Europe/London')::int as hora,
        count(*) as n
    from {{ ref('stg_viagens') }}, janela
    where inicio_local >= inicio_janela and inicio_local < fim_janela
      and estacao_fim_terminal is not null and fim is not null
    group by 1, 2, 3
),

grade as (
    select terminal, dia_semana, hora from retiradas
    union
    select terminal, dia_semana, hora from devolucoes
)

select
    g.terminal,
    g.dia_semana,
    g.hora,
    round(coalesce(r.n, 0)::numeric / d.n_dias, 4) as retiradas_media,
    round(coalesce(v.n, 0)::numeric / d.n_dias, 4) as devolucoes_media
from grade g
join dias d using (dia_semana)
left join retiradas r using (terminal, dia_semana, hora)
left join devolucoes v using (terminal, dia_semana, hora)
