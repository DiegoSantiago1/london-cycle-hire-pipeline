# SQL no data lake: Glue Data Catalog + Athena (D50)

O bruto ao vivo fica no S3 do jeito que a API da TfL devolveu: um arquivo `.json.gz` por coleta,
em `bruto/bikepoint/data=AAAA-MM-DD/`. O Athena consulta esses arquivos com SQL, sem carregar nada
num banco e sem mudar o bruto.

```
S3 (bruto intocado) ──► Glue Data Catalog: tabela `retratos` (uma linha de texto por arquivo)
                          └─► view `estacoes`: json_parse + UNNEST → uma linha por estação por coleta
                          └─► view `coletas`:  uma linha por coleta, com o atraso do agendador
```

## Como funciona

- **Tabela sem crawler** (`infra/athena.tf`). Cada retrato é uma lista JSON numa linha só (2,2 MB,
  ~800 estações). A tabela lê essa linha como texto, numa coluna só (`linha`), e quem abre o JSON é a
  view. Se a TfL acrescentar um campo, nada quebra.
- **Projeção de partições.** O Athena calcula as partições pelo nome da pasta (`data=AAAA-MM-DD`),
  sem crawler e sem `MSCK REPAIR`. Filtrar por `data` faz o Athena ler só aquelas pastas.
- **Mesmas regras do dbt** (`dbt/models/staging/stg_retratos.sql`): vazia = 0 bicicletas, cheia = 0
  vagas livres, em operação = instalada e não bloqueada.
- **Horário da coleta pelo nome do arquivo** (`bikepoint_AAAA-MM-DDTHH-MM-SSZ.json.gz`), lido pela
  pseudo-coluna `"$path"`. Um teste quebra se a coleta mudar o formato do nome.
- **Trava de custo.** O grupo de trabalho `london-cycle-hire` recusa consulta que leia mais de 1 GB e
  guarda os resultados num bucket separado, criptografado e apagado em 7 dias.

## Como rodar

Precisa de `aws login` (ou do OIDC no GitHub Actions).

```bash
bash scripts/athena.sh athena/01_view_estacoes.sql athena/02_view_coletas.sql   # cria/atualiza as views
bash scripts/athena.sh athena/consultas/atraso_agendador.sql                    # roda uma consulta
```

O script espera a consulta terminar, mostra o resultado e quanto foi lido (o que o Athena cobra).

| Consulta (`athena/consultas/`) | Pergunta |
|---|---|
| `atraso_agendador.sql` | Quantas coletas por dia e com quanto atraso o EventBridge Scheduler dispara |
| `vazias_por_hora.sql` | Em que hora do dia (Londres) as estações mais ficam vazias ou cheias, dia útil × fim de semana |
| `estacoes_mais_vazias.sql` | As 15 estações que mais tempo passaram sem bicicleta nos últimos 7 dias |
| `conferencia.sql` | Contagens de ontem, para conferir contra uma contagem independente em Python |

## Resultados medidos (21/10/2026)

**Conferência.** Para 20/10, o Athena e uma contagem independente em Python sobre os mesmos 96
arquivos baixados do S3 deram exatamente os mesmos números:

| retratos | linhas (estação × coleta) | estações distintas | soma de bicicletas | vazias | cheias |
|---|---|---|---|---|---|
| 96 | 76.846 | 801 | 779.905 | 8.996 | 4.318 |

**Agendador.** De 15/10 a 20/10, o EventBridge Scheduler disparou **96 de 96 janelas por dia**, com
atraso mediano de **20 s** (máximo de 21 s). O dia 14/10 tem 87 coletas porque a Lambda entrou no ar
às 02:23 UTC. O cron do GitHub Actions, antes da migração, rodou de 4 a 5 janelas por dia (D45).

**Poda de partições.** A conferência de um dia leu **7,7 MB**; a base inteira (14 a 21/10) tem
**59 MB**. Uma consulta na base inteira custa cerca de **US$ 0,0003**.

**O que os dados mostram** (14 a 21/10, estações em operação):
- Nos dias úteis, a proporção de estações vazias é maior de madrugada (16% a 18% entre 22h e 3h) e
  menor no meio da tarde (5,5% às 15h).
- As estações que mais tempo passaram vazias ficam no centro: Portugal Street (Holborn, 49,6% do
  tempo), Houghton Street (Strand, 48,9%) e Fore Street (Guildhall, 47,1%).

São só 8 dias de dados: os percentuais servem para mostrar o que a camada responde, não como
conclusão sobre a operação.
