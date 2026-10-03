# Decisões — london-cycle-hire-pipeline

Cada decisão tem o motivo e a alternativa descartada. Datas no formato DD/MM/AAAA.

| # | Data | Decisão | Por quê | Alternativa descartada |
|---|---|---|---|---|
| D1 | 03/10/2026 | Fonte: bicicletas públicas de Londres (TfL) | Tem lote (viagens) + ao vivo (API), problema de negócio claro (rebalanceamento) e liga o portfólio a Londres | Energia do ONS (plano B), clima, cripto, voos |
| D2 | 03/10/2026 | Python no pipeline, dbt nas transformações | Python é o padrão de Dados; dbt traz camadas, testes e linhagem em SQL | Node/TS: nada no projeto pede |
| D3 | 03/10/2026 | Sem API Node/TS | O resultado é uma página estática; uma API não teria quem consumisse e exigiria servidor 24 h | API Express (fica para o Projeto 5) |
| D4 | 03/10/2026 | Tecnologias novas limitadas a três: dbt, Terraform, AWS | Foco; cada uma com função real | Airflow, DuckDB, Parquet etc. |
| D5 | 03/10/2026 | Nuvem só na fase 7; até lá, coleta escrita como handler de Lambda e bruto com as mesmas chaves do S3 | A conta ainda não existe; assim a migração não tem retrabalho | Esperar a conta para começar (perderia histórico) |
| D6 | 03/10/2026 | Sem RDS | Cobra por hora; o banco fica local e no Actions | RDS |
| D7 | 03/10/2026 | Repositório `london-cycle-hire-pipeline` | "Cycle hire" é o termo oficial da TfL e do Reino Unido | `london-bike-pipeline` |
| D8 | 03/10/2026 | Código em português; prefixos do dbt no padrão (`stg_`, `int_`, `fct_`, `dim_`) | Escolha do Diego (mais fácil de estudar e explicar); os prefixos são vocabulário que todo entrevistador reconhece | Código em inglês (recomendação inicial) |
| D9 | 03/10/2026 | README em inglês (principal) + português | Alvo Londres sem perder o público brasileiro | Só um idioma |
| D10 | 03/10/2026 | dbt-core 1.12 + dbt-postgres 1.11 no Python 3.14, numa `.venv` só | Medido: instala e `dbt parse` passa no 3.14 | `.venv` separada com Python 3.12 |
| D11 | 03/10/2026 | Bruto ao vivo em GitHub Releases (1 release por dia) até a nuvem existir | Grátis, permanente e fora do histórico do git | Branch de dados (incha o git: ~2,8 GB/ano); artifacts (expiram em 90 dias) |
| D12 | 03/10/2026 | Guardar o retrato completo da API, intocado (79 KB gzip) | Princípio do data lake: tudo se recalcula a partir do bruto, e campo descartado não volta | Só os campos usados (12 KB) |
| D13 | 03/10/2026 | Coleta a cada 15 min, nos minutos 7, 22, 37 e 52 | Precisão de ±15 min; o GitHub atrasa mais na virada da hora | 10 min (ganho some com o atraso); 30 min (perde esvaziamentos curtos) |
| D14 | 03/10/2026 | Viagens de jan/2022 até o arquivo mais recente | Atravessa a mudança de formato (set/2022) e cobre vários anos de sazonalidade sem pesar demais | Só 12 meses (perde a mudança de formato); desde 2015 (15 GB) |
| D15 | 03/10/2026 | CSVs de viagens fora do OneDrive (variável `BICICLETAS_DADOS`) | Evita sincronizar gigabytes; o bruto pode ser baixado de novo da TfL | `data/raw/` dentro da pasta |
| D16 | 03/10/2026 | Dois ritmos: viagens no PC (carga incremental) e ao vivo no Actions (banco temporário recriado todo dia) | O Actions não guarda banco; as viagens são pesadas e raras, a parte ao vivo é leve e diária | Tudo no PC (página não se atualizaria sozinha); PostgreSQL hospedado grátis (não comporta as viagens) |
| D17 | 03/10/2026 | Ranking por demanda perdida estimada | Fala a língua do negócio e diferencia estação vazia às 3 h de estação vazia às 8 h | Só horas vazias/cheias |
| D18 | 03/10/2026 | Vazia = `NbBikes = 0`; cheia = `NbEmptyDocks = 0`; falta de clássicas é indicador secundário | Medido: em 625 de 799 estações, bicicletas + vagas ≠ docas, então não dá para depender de `NbDocks` | Vazia = zero clássicas |
| D19 | 03/10/2026 | Carregador lê CSV pelo nome da coluna e recusa cabeçalho desconhecido | Medido: 6 variantes de cabeçalho, inclusive colunas trocadas de ordem | Leitura por posição |
| D20 | 03/10/2026 | Ligação das estações por número + nome normalizado | Medido: número antigo reaproveitado (`327`) | Ligar só pelo número |
| D21 | 03/10/2026 | Horários em `timestamptz`; viagens interpretadas em `Europe/London`, API em UTC | Lição do Projeto 3; o horário de verão cria uma hora repetida em outubro | `timestamp` sem fuso |
| D22 | 03/10/2026 | Página de apresentação moderna em capítulos (como a do Projeto 3), com mapa, ranking/perfil, fluxos e saúde do pipeline; é o link do portfólio | Pedido do Diego: todo projeto tem uma página para mostrar resultados a recrutadores | Só README ou só Power BI |
| D23 | 03/10/2026 | Teto de 80 h; primeiro corte se estourar: fluxos no mapa viram tabela | As 6 variantes de cabeçalho e os dois ritmos somaram trabalho à estimativa de 70 h | Manter 70 h e cortar agora |
| D24 | 03/10/2026 | A coleta (`coleta_api.py`) e o pacote diário usam só a biblioteca padrão do Python | Rodam no Actions sem `pip install` (execução rápida) e a coleta vira Lambda na fase 7 sem empacotar dependências | `requests`/`httpx` |
| D25 | 03/10/2026 | Resposta sem a forma de BikePoint (não é JSON, não é lista, menos de 100 estações, estação sem `NbBikes`/`NbEmptyDocks`/`NbDocks`/`TerminalName`) é falha de coleta e não vai para o bruto; o começo da resposta vai para o log como evidência. Resposta com a forma certa é gravada como veio, mesmo com valores estranhos | Página de erro no bruto contaminaria todas as cargas; julgar valores é papel dos testes do dbt | Guardar qualquer HTTP 200 |
| D26 | 03/10/2026 | Cada execução grava um registro (`bruto/execucoes_coleta/...`): sucesso ou falha, evento que disparou, id da execução, estações, hash. Mesmo carimbo do retrato | O GitHub apaga o histórico de execuções em 90 dias; o registro fica para sempre e é a base da medição do atraso do agendador (só eventos `schedule` contam) | Consultar a API do GitHub depois |
| D27 | 03/10/2026 | Pacote diário: `.tar` determinístico com os arquivos originais do dia (UTC) + manifesto com hashes, conferido antes de publicar; os originais continuam na release | O job diário baixa 28 pacotes em vez de ~2.700 arquivos; mesmo conteúdo gera o mesmo pacote (idempotente) | Apagar os originais depois de empacotar |
| D28 | 03/10/2026 | CI com PostgreSQL de verdade (service container) rodando o mesmo `bootstrap.sql`; avisos do pytest viram erro | Os testes de banco rodam a cada push, não só na máquina local; o "aviso = erro" já pegou um `HTTPError` não fechado na coleta | CI só com testes unitários |
| D29 | 03/10/2026 | Retratos consecutivos podem ser idênticos: a análise usa o `modified` de cada estação e o instante da coleta, e trata retrato repetido | Medido: 3 coletas em 8 s vieram byte a byte iguais (API em cache); a idade do dado no momento da coleta tinha mediana de 19 min (p90 78 min). Medir com a coleta rodando quantas vezes por hora o conteúdo muda | Supor que cada retrato é um estado novo |
