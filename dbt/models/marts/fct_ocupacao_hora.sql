{#
  Minutos observados, vazia, cheia e sem bicicleta clássica por estação e hora de
  Londres. Os intervalos que atravessam a virada da hora são divididos entre as duas
  horas. Só conta tempo de estação em operação (instalada e não bloqueada).
  O fuso é fixado na própria consulta (lição do Projeto 3: não depender da sessão).
#}
{{ config(tags=['diario']) }}

with intervalos as (
    select * from {{ ref('int_ocupacao_intervalos') }} where em_operacao
),

partes as (
    select
        i.estacao_id,
        i.terminal,
        h as hora_utc,
        extract(epoch from least(i.fim, h + interval '1 hour') - greatest(i.inicio, h)) / 60.0
            as minutos,
        i.vazia,
        i.cheia,
        i.sem_classica
    from intervalos i
    cross join lateral generate_series(
        date_trunc('hour', i.inicio, 'UTC'),
        i.fim - interval '1 microsecond',
        interval '1 hour'
    ) as h
)

select
    estacao_id,
    terminal,
    (hora_utc at time zone 'Europe/London')::date as data_local,
    extract(hour from hora_utc at time zone 'Europe/London')::int as hora,
    extract(isodow from hora_utc at time zone 'Europe/London')::int as dia_semana,
    hora_utc,
    round(sum(minutos)::numeric, 2) as minutos_observados,
    round(coalesce(sum(minutos) filter (where vazia), 0)::numeric, 2) as minutos_vazia,
    round(coalesce(sum(minutos) filter (where cheia), 0)::numeric, 2) as minutos_cheia,
    round(coalesce(sum(minutos) filter (where sem_classica), 0)::numeric, 2) as minutos_sem_classica
from partes
group by 1, 2, 3, 4, 5, 6
