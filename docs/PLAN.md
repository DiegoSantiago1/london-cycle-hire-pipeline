# PLAN — london-cycle-hire-pipeline

## Estado (03/10/2026, noite)

| Fase | Situação |
|---|---|
| 0 Grill + medições | Feita |
| 1 Fundação | Feita |
| 2 Coleta ao vivo | No ar desde 03/10/2026 (2 coletas manuais conferidas; as agendadas ainda não tinham começado no fim do dia) |
| 3 Viagens | Feita: 148 arquivos, 41.376.421 viagens, 0 recusados |
| 4 dbt | Feita: 16 modelos, 47 testes |
| 5 Job diário | Feito e publicado (recria o banco do zero e publica no Pages) |
| 6 Página | Publicada: https://diegosantiago1.github.io/london-cycle-hire-pipeline/ |
| 7 Nuvem + Terraform | **Pendente**: depende da conta na nuvem |
| 8 Fechamento | README EN/PT feito; revisões e portfólio em andamento |

O que mudou em relação ao plano original, com o motivo: D31 a D41 em [DECISOES.md](DECISOES.md).

> Plano escrito em 03/10/2026, depois do grill. As decisões e o motivo de cada uma estão em [DECISOES.md](DECISOES.md). Números marcados com **(medido)** foram medidos em 03/10/2026; os marcados com **(estimativa)** ainda precisam ser medidos.

## 1. Problema

As bicicletas públicas de Londres (TfL Santander Cycles) têm um problema operacional diário: **rebalanceamento**. De manhã as estações residenciais esvaziam e as do centro lotam; à tarde, o inverso. Estação vazia é viagem que não acontece; estação cheia é usuário que não consegue devolver.

Perguntas de negócio:

1. Quais estações ficam vazias ou cheias, e em que horários?
2. Quanto tempo por dia cada estação passa sem bicicleta (ou sem vaga)?
3. Quais são os fluxos origem → destino por hora e dia da semana?
4. Onde a operação deveria agir primeiro? Ranking por **demanda perdida estimada**.

O desafio de engenharia: o dado **não para de chegar**. Por isso o projeto tem carga incremental, idempotência (rodar duas vezes não duplica), bruto guardado intocado, testes de qualidade, freshness e execução agendada.

## 2. Fontes (medido)

| Fonte | O que é | Ritmo | Volume |
|---|---|---|---|
| API `https://api.tfl.gov.uk/BikePoint` | Estado atual das 799 estações: bicicletas, vagas, docas, clássicas, elétricas | Ao vivo, sem chave | 2,2 MB por retrato, 79 KB em gzip |
| Bucket `cycling.data.tfl.gov.uk/usage-stats/` | Arquivos de viagens (uma linha por aluguel) | Um CSV a cada ~15 dias, publicado com meses de atraso, às vezes republicado | 474 CSV, 15,3 GB no total, ~1,3–1,5 GB/ano |

O que a medição revelou e o plano precisa tratar:

- **Seis variantes de cabeçalho** nos CSVs. A virada grande foi entre o arquivo 332 (ago/2022) e o 335 (set/2022): `Rental Id, Duration, ... StartStation Id` virou `"Number", "Start date", ... "Total duration (ms)"`. Também há colunas trocadas de ordem, arquivo sem aspas, `Duration_Seconds` e vírgulas sobrando. **O carregador lê pelo nome da coluna, nunca pela posição, e recusa cabeçalho desconhecido.**
- Datas: antigo `10/01/2016 00:04` (às vezes com segundos), novo `2026-05-31 23:59`. Sem fuso: horário de Londres.
- Numeração das estações: a antiga (`18`) bate com o `id` da API (`BikePoints_18`) em 235 de 256 estações; a nova (`001083`) bate com o `TerminalName` em 790 de 796. **Há número antigo reaproveitado** (`327` era "New North Road 1" e hoje é "Westbourne Green"), então a ligação não pode ser só pelo número.
- API: em 625 de 799 estações, bicicletas + vagas ≠ docas (docas fora de serviço). Por isso **vazia = `NbBikes = 0`** e **cheia = `NbEmptyDocks = 0`**, sem depender de `NbDocks`.
- Licença: Open Government Licence v2.0 adaptada pela TfL. Atribuição obrigatória "Powered by TfL Open Data"; não usar logo nem parecer oficial. **Antes de publicar, conferir os termos no navegador** (a página bloqueou o acesso automatizado).

## 3. Arquitetura: dois ritmos

```
                 a cada 15 min (minutos 7, 22, 37, 52)
 API BikePoint ──► coleta (handler estilo Lambda) ──► bruto intocado (.json.gz)
                                                       GitHub Releases, 1 release por dia
                                                       (fase 7: S3, mesmas chaves)

                 1x por dia (GitHub Actions)
 últimos 28 dias de retratos ─┐
 agregados das viagens (repo) ├─► PostgreSQL temporário ─► dbt build + testes ─► exportador ─► página (GitHub Pages)
 histórico de execuções ──────┘     (recriado do zero)       + source freshness    (recusa se
                                                                                   teste falhar)

                 quando sai arquivo novo da TfL (no PC)
 bucket TfL ──► download (ETag) ──► carga incremental ──► PostgreSQL local ──► dbt ──► agregados pequenos (CSV no repo)
                 (fora do OneDrive)   (tabela de controle)  (container compartilhado)
```

**Por que dois ritmos:** o GitHub Actions não guarda banco entre execuções e não teria como manter dezenas de milhões de viagens. As viagens são pesadas e chegam raramente, então são processadas no PC. A parte ao vivo é leve e precisa rodar todo dia, então vai para o Actions. O job diário recria o banco do zero a partir do bruto, o que prova na prática que o pipeline é reprodutível e idempotente.

### 3.1 Chaves do bruto (iguais às do S3 futuro)

- Retrato: `bruto/bikepoint/data=AAAA-MM-DD/bikepoint_AAAA-MM-DDTHH-MM-SSZ.json.gz` (horário UTC da coleta).
  - Em Releases: tag `bruto-bikepoint-AAAA-MM-DD`; o nome do arquivo é a chave sem barras.
  - Pacote diário: um `.tar` com os ~96 arquivos originais, byte a byte, conferido por hash. Serve para o job diário baixar 28 arquivos em vez de ~2.700.
- Viagens: `bruto/viagens/<nome original do arquivo>.csv`, numa pasta fora do OneDrive. O caminho vem da variável de ambiente `BICICLETAS_DADOS`.

### 3.2 Banco

PostgreSQL 16 no container compartilhado `honda-vendas-db`, só local, com usuário e banco próprios. Tabelas da camada bruta e de controle criadas por migrations Alembic com SQL à mão; o resto é dbt.

| Schema | Conteúdo | Quem cria |
|---|---|---|
| `bruto` | `retratos` (uma linha por estação por retrato, campos como texto, com a chave do arquivo de origem) e `viagens` (como veio, campos como texto, com o arquivo de origem) | Alembic + carregadores Python |
| `controle` | `arquivos_viagens` (chave, ETag, tamanho, cabeçalho, linhas, carregado_em) e `execucoes_coleta` (execuções do cron: previsto × real, status) | Alembic + carregadores |
| `agregados` | Agregados das viagens trazidos do CSV do repositório (mesmo caminho no PC e no Actions) | Carregador |
| `staging`, `intermediario`, `marts` | Modelos dbt | dbt |

### 3.3 Modelos dbt (rascunho)

- **staging:** `stg_retratos` (tipos, `timestamptz` UTC), `stg_viagens` (unifica as variantes, datas em `Europe/London`, duração em segundos, dedup por número do aluguel quando um arquivo republicado se sobrepõe a outro: medir antes de decidir a regra), `stg_estacoes_api`.
- **intermediário:**
  - `int_ligacao_estacoes`: número antigo → `BikePoints_N` → `TerminalName`, só quando o nome normalizado também bate. As exceções ficam listadas e medidas.
  - `int_intervalos_ocupacao`: cada retrato vale até o próximo, limitado a 30 min. Execução pulada vira "sem observação", nunca "vazia".
- **marts:** `dim_estacoes`, `fct_ocupacao_estacao_hora` (minutos vazia, cheia e observados), `agg_demanda_estacao_hora` (retiradas e devoluções médias por estação × dia da semana × hora, últimos 12 meses de viagens), `agg_fluxos_hora` (principais pares origem → destino), `mart_demanda_perdida` e `mart_ranking`.
- **Demanda perdida estimada** = minutos vazia naquela estação, dia e hora × taxa típica de retiradas ali naquele dia da semana e hora. O mesmo vale para cheia × devoluções. É **estimativa**, e a página diz isso.
- **Testes:**
  - genéricos (`not_null`, `unique`, `relationships`, `accepted_values`);
  - específicos (bicicletas ≥ 0, clássicas + elétricas = total, minutos vazia ≤ minutos observados, toda viagem com estação ligada ou marcada como sem ligação);
  - `dbt source freshness` nas duas fontes (retratos: alerta com 1 h, erro com 3 h; viagens: limites a definir medindo o atraso real da TfL).

### 3.4 Página de apresentação (GitHub Pages)

É o produto que o recrutador vê: o link que vai no portfólio e no README. Endereço previsto: **https://diegosantiago1.github.io/london-cycle-hire-pipeline/**.

Tem de ser uma página moderna e bem visual, em capítulos, como a do Projeto 3 (customer-analytics-online-retail). Ela conta o problema, mostra os resultados e explica como o pipeline funciona, e se atualiza sozinha todo dia. Tecnicamente: HTML/CSS/JS sem build, Leaflet + mapa base OpenStreetMap/CARTO com atribuição, Chart.js, alternância inglês/português e claro/escuro, navegação pelas setas do teclado e layout que funciona no celular.

1. **Mapa de risco por hora:** estações coloridas por % do tempo vazia ou cheia nos últimos 7 dias, com controle de hora do dia.
2. **Ranking + perfil da estação:** onde agir primeiro; clicar mostra o perfil por hora.
3. **Fluxos origem → destino** por hora (no mapa; se o tempo apertar, vira tabela).
4. **Saúde do pipeline:** última coleta, atraso do cron (previsto × real), execuções falhas, freshness, testes.

Rodapé com "Powered by TfL Open Data" e a atribuição do mapa.

## 4. Fases e horas (teto: 80 h)

| # | Fase | Entrega | Horas |
|---|---|---|---|
| 0 | Grill + medições | Este plano, DECISOES.md, medições | 3 (feito) |
| 1 | Fundação | git, `.venv`, `requirements.txt`, ruff + mypy + pytest, Alembic, usuário e banco no container | 4 |
| 2 | **Coleta ao vivo no ar** (prioridade: cada dia parado é histórico perdido) | Handler estilo Lambda, tentativas com espera, upload para Releases, pacote diário, registro das execuções, testes (inclusive API fora do ar e resposta estranha) | 8 |
| 3 | Viagens | Listagem do bucket, download por ETag, carga incremental pelas 6 variantes, tabela de controle, rodar duas vezes sem duplicar, arquivo republicado recarregado, testes hostis | 12 |
| 4 | dbt | Fontes, staging, ligação das estações, intermediários, marts, testes, freshness, agregados exportados | 15 |
| 5 | Job diário | Actions com PostgreSQL temporário, carga dos 28 dias, dbt build, saúde do pipeline, exportador que recusa dado reprovado, proteção contra o desligamento de 60 dias | 10 |
| 6 | Página | Mapa, ranking/perfil, fluxos, saúde, EN/PT, publicada | 12 |
| 7 | Nuvem + Terraform (quando a conta existir) | Lambda + EventBridge Scheduler + S3 + IAM mínimo + OIDC + CloudWatch + Budgets, cópia do histórico, medição do atraso antes × depois | 8 |
| 8 | Fechamento | README EN/PT (com "Access the project" / "Acessar o projeto" apontando para a página), três revisões (engenharia, QA, dados), conferência de cada número, card no portfólio com "Abrir projeto" → página, seção no README de perfil | 8 |

Total: 80 h, cerca de 5 semanas a 15–20 h/semana. **Se estourar, o primeiro corte é a seção de fluxos no mapa, que vira tabela.**

A fase 2 vem antes da 3 de propósito: assim a coleta acumula histórico enquanto o resto é construído. **O repositório precisa ser público já na fase 2.** Em repositório privado, 96 execuções por dia gastariam mais que os 2.000 minutos grátis do Actions.

## 5. Riscos

| Risco | Como tratar |
|---|---|
| Cron do Actions atrasa ou pula execuções | Registrar previsto × real desde o primeiro dia; usar minutos fora da virada da hora; execução pulada vira "sem observação". A medição justifica a migração da fase 7. |
| Workflow agendado desligado após 60 dias sem atividade (repo público) | Job diário faz um commit mensal de manutenção (decidir o mecanismo na fase 5); alerta se a última coleta tiver mais de 3 h. |
| API fora do ar ou com formato novo | Até 3 tentativas com espera (5 s, 10 s); se falhar, o job fica vermelho, o GitHub manda e-mail e o registro da execução guarda o erro. Resposta sem a forma de BikePoint não vai para o bruto (D25); com a forma certa, é guardada como veio e os valores são julgados pelos testes do dbt. |
| TfL republica arquivo de viagens | ETag na tabela de controle; arquivo com ETag novo é recarregado (apaga as linhas daquele arquivo e insere de novo, na mesma transação). |
| Viagens repetidas entre arquivos | Medir antes de deduplicar (lição do Projeto 3: duplicata pode ser artefato ou dado real). |
| Hora repetida no fim do horário de verão (01:00–02:00 duas vezes) | Medir quantas viagens caem nessa hora; decidir e documentar a regra. |
| Número de estação reaproveitado | Ligação por número + nome; exceções listadas. |
| OneDrive sincronizando gigabytes | Bruto das viagens fora do OneDrive. |
| Licença | Atribuição na página e no README; conferir os termos antes de publicar. |

## 6. Fora do escopo (de propósito)

- API Node/TS: não há quem consumiria; servidor 24 h custaria sem motivo. Fica para o Projeto 5.
- RDS, EC2, ECS, VPC, SQS: sem função real aqui.
- Previsão com machine learning e viagens anteriores a 2022.
- Qualquer tecnologia nova além de dbt, Terraform e AWS.

## 7. O que o projeto deve permitir responder em entrevista

- Como rodar duas vezes não duplica (viagens e retratos)?
- A fonte mudou o formato: como percebeu e o que fez?
- Por que guardar o bruto se já existe PostgreSQL?
- Como sabe que o dado de hoje chegou (freshness)?
- ETL × ELT, e por que dbt?
- Como o cron atrasava, quanto, e o que a migração mudou?
- Como controlou custo e permissão na nuvem?
- O que é "demanda perdida estimada" e qual a limitação dela?
