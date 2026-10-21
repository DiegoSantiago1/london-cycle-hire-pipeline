-- Conferência: o que o Athena lê de ontem (UTC) tem que bater com a contagem feita em
-- Python sobre os mesmos arquivos da release pública (scripts/conferir_athena.py).
SELECT
    data,
    count(DISTINCT arquivo) AS retratos,
    count(*) AS linhas_estacao,
    count(DISTINCT estacao_id) AS estacoes_distintas,
    sum(bicicletas) AS soma_bicicletas,
    count_if(vazia) AS vazias,
    count_if(cheia) AS cheias
FROM estacoes
WHERE data = CAST(current_date - INTERVAL '1' DAY AS VARCHAR)
GROUP BY data
