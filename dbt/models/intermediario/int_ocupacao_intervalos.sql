{#
  Cada retrato de uma estação vale do momento da coleta até o retrato seguinte, com
  teto de 30 min. Se a coleta falhou ou atrasou, o tempo além do teto fica "sem
  observação" (nunca é contado como vazia ou cheia). O último retrato de cada estação
  ainda não tem sucessor e fica de fora até a próxima coleta (conservador).
#}
{{ config(tags=['diario']) }}

with ordenados as (
    select
        estacao_id,
        terminal,
        coletado_em,
        vazia,
        cheia,
        sem_classica,
        em_operacao,
        lead(coletado_em) over (partition by estacao_id order by coletado_em) as proxima
    from {{ ref('stg_retratos') }}
)

select
    estacao_id,
    terminal,
    coletado_em as inicio,
    least(proxima, coletado_em + interval '30 minutes') as fim,
    vazia,
    cheia,
    sem_classica,
    em_operacao
from ordenados
where proxima is not null
