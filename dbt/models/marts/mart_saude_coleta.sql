{#
  Saúde da coleta por dia (UTC): execuções agendadas, falhas, janelas do cron sem
  nenhuma coleta e atraso do agendador (só as execuções agendadas medem atraso: EventBridge
  + Lambda, cron do GitHub ou agendador externo; as manuais ficam de fora). Foi esta medição
  que justificou tirar a coleta do cron do GitHub e levar para a AWS (D45):
  janelas_lambda conta as janelas em que a Lambda coletou.
#}
{{ config(tags=['diario']) }}

with execucoes as (
    select *, (iniciado_em at time zone 'UTC')::date as dia
    from {{ ref('stg_execucoes_coleta') }}
),

primeira_agendada as (
    select min(previsto_em) as desde from execucoes where agendada
),

janelas as (
    -- todas as janelas do cron (minutos 7, 22, 37, 52) desde a primeira execução agendada
    select j as previsto_em, (j at time zone 'UTC')::date as dia
    from primeira_agendada,
        generate_series(desde, (select max(iniciado_em) from execucoes), interval '15 minutes') as j
    where desde is not null
),

agendadas as (
    select
        previsto_em,
        min(iniciado_em) as iniciado_em,
        bool_or(status = 'sucesso') as sucesso,
        bool_or(origem = 'aws_lambda' and status = 'sucesso') as pela_lambda
    from execucoes
    where agendada
    group by 1
),

por_dia as (
    select
        j.dia,
        count(*) as janelas,
        count(a.previsto_em) as janelas_com_execucao,
        count(*) filter (where a.sucesso) as janelas_com_sucesso,
        count(*) filter (where a.pela_lambda) as janelas_lambda,
        percentile_cont(0.5) within group (
            order by extract(epoch from a.iniciado_em - a.previsto_em) / 60.0
        ) as atraso_mediano_min,
        percentile_cont(0.9) within group (
            order by extract(epoch from a.iniciado_em - a.previsto_em) / 60.0
        ) as atraso_p90_min,
        max(extract(epoch from a.iniciado_em - a.previsto_em) / 60.0) as atraso_max_min
    from janelas j
    left join agendadas a using (previsto_em)
    group by 1
),

totais as (
    select
        dia,
        count(*) as execucoes,
        count(*) filter (where status = 'falha') as falhas,
        count(*) filter (where not agendada) as manuais
    from execucoes
    group by 1
)

select
    t.dia,
    t.execucoes,
    t.falhas,
    t.manuais,
    coalesce(p.janelas, 0) as janelas,
    coalesce(p.janelas_com_execucao, 0) as janelas_com_execucao,
    coalesce(p.janelas_com_sucesso, 0) as janelas_com_sucesso,
    coalesce(p.janelas_lambda, 0) as janelas_lambda,
    round(p.atraso_mediano_min::numeric, 1) as atraso_mediano_min,
    round(p.atraso_p90_min::numeric, 1) as atraso_p90_min,
    round(p.atraso_max_min::numeric, 1) as atraso_max_min
from totais t
left join por_dia p using (dia)
