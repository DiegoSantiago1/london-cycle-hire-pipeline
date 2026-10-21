-- View `estacoes`: uma linha por estação em cada retrato do bruto (D50).
--
-- A tabela `retratos` (infra/athena.tf) lê cada arquivo .json.gz como uma linha de texto.
-- Aqui o JSON é aberto: json_parse transforma a linha numa lista e o UNNEST faz de cada
-- estação uma linha. As regras são as mesmas do dbt (dbt/models/staging/stg_retratos.sql):
-- vazia = 0 bicicletas, cheia = 0 vagas livres, em operação = instalada e não bloqueada.
-- O horário da coleta vem do nome do arquivo (bikepoint_AAAA-MM-DDTHH-MM-SSZ.json.gz).
CREATE OR REPLACE VIEW estacoes AS
WITH lidos AS (
    SELECT
        data,
        "$path" AS arquivo,
        date_parse(
            regexp_extract("$path", 'bikepoint_([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2})Z', 1),
            '%Y-%m-%dT%H-%i-%s'
        ) AS coletado_em_utc,
        CAST(json_parse(linha) AS ARRAY(JSON)) AS lista
    FROM retratos
),
por_estacao AS (
    SELECT
        l.data,
        l.arquivo,
        l.coletado_em_utc,
        e AS estacao,
        -- additionalProperties é uma lista de {key, value}: vira um mapa chave → valor.
        map_from_entries(
            transform(
                CAST(json_extract(e, '$.additionalProperties') AS ARRAY(MAP(VARCHAR, VARCHAR))),
                p -> ROW(p['key'], p['value'])
            )
        ) AS prop
    FROM lidos AS l
    CROSS JOIN UNNEST(l.lista) AS t (e)
)
SELECT
    data,
    coletado_em_utc,
    CAST(with_timezone(coletado_em_utc, 'UTC') AT TIME ZONE 'Europe/London' AS TIMESTAMP) AS coletado_em_londres,
    json_extract_scalar(estacao, '$.id') AS estacao_id,
    prop['TerminalName'] AS terminal,
    trim(json_extract_scalar(estacao, '$.commonName')) AS nome,
    CAST(json_extract_scalar(estacao, '$.lat') AS DOUBLE) AS lat,
    CAST(json_extract_scalar(estacao, '$.lon') AS DOUBLE) AS lon,
    TRY_CAST(prop['NbBikes'] AS INTEGER) AS bicicletas,
    TRY_CAST(prop['NbEmptyDocks'] AS INTEGER) AS vagas_livres,
    TRY_CAST(prop['NbDocks'] AS INTEGER) AS docas,
    TRY_CAST(prop['NbStandardBikes'] AS INTEGER) AS classicas,
    TRY_CAST(prop['NbEBikes'] AS INTEGER) AS eletricas,
    prop['Installed'] = 'true' AS instalada,
    prop['Locked'] = 'true' AS bloqueada,
    prop['Temporary'] = 'true' AS temporaria,
    TRY_CAST(prop['NbBikes'] AS INTEGER) = 0 AS vazia,
    TRY_CAST(prop['NbEmptyDocks'] AS INTEGER) = 0 AS cheia,
    prop['Installed'] = 'true' AND prop['Locked'] = 'false' AS em_operacao,
    arquivo
FROM por_estacao
