# London Cycle Hire Pipeline

**Onde as bicicletas públicas de Londres acabam, e onde a operação deve agir primeiro?** Pipeline de dados das TfL Santander Cycles: retratos de todas as estações a cada 15 minutos, 41 milhões de viagens publicadas, PostgreSQL e dbt, e uma página de resultados recriada do zero todo dia.

## 🔗 Acessar o projeto

[![Abrir o projeto](https://img.shields.io/badge/%E2%96%B6%20Abrir%20o%20projeto-EA580C?style=for-the-badge)](https://diegosantiago1.github.io/london-cycle-hire-pipeline/)
[![Ver no portfólio](https://img.shields.io/badge/Ver%20no%20portf%C3%B3lio-1F2937?style=for-the-badge&logo=googlechrome&logoColor=white)](https://diegosantiago1.github.io/Portifolio/#projetos)

**Link direto:** https://diegosantiago1.github.io/london-cycle-hire-pipeline/

Uma página interativa em português e inglês que abre no navegador, sem instalar nada: um mapa que você move hora a hora, as estações ordenadas pelas viagens que devem perder e a saúde do próprio pipeline, ao vivo.

[English](README.md) · [Plano](docs/PLAN.md) · [Decisões e medições (D1–D43)](docs/DECISOES.md)

![Fluxos da manhã: às 8h as maiores ligações saem de Waterloo para a City](docs/img/mapa_fluxos.png)

## O problema

As bicicletas públicas de Londres têm um problema operacional diário: o **rebalanceamento**. De manhã as estações residenciais esvaziam e as do centro lotam; à tarde, o inverso. Estação vazia é viagem que não acontece; estação cheia é gente que não consegue devolver a bicicleta.

O pipeline responde quatro perguntas:

1. Quais estações ficam vazias ou cheias, e em que horários?
2. Quanto tempo cada estação passa sem bicicleta (ou sem vaga)?
3. Quais são os fluxos origem → destino, hora a hora?
4. Onde a operação deve agir primeiro? As estações são ordenadas pela **demanda perdida estimada**: horas vazia × quantas pessoas costumam pegar bicicleta ali naquela hora (e o mesmo para estação cheia e devoluções).

O desafio de engenharia é que **o dado não para de chegar**: carga incremental, idempotência (rodar duas vezes nunca duplica), bruto intocado, testes de qualidade, freshness e execução agendada.

## O que os dados mostram

- **O trajeto casa–trabalho aparece nos fluxos.** Num dia útil médio, a maior ligação às 8h é Waterloo Station 3 → Queen Street (Bank), cerca de 3,2 viagens por dia útil; às 17h a maior é St Paul's → Waterloo Station 3. As bicicletas saem do terminal de trem de manhã e voltam à tarde.
- **As elétricas foram de 0 a 19,5% das viagens** (maio de 2026). As primeiras viagens de elétrica nos arquivos são de 14 de setembro de 2022.
- **A TfL trocou o sistema de dados em setembro de 2022**, e os arquivos mostram isso: dois dias quase sem viagens (10 e 11/09/2022) e um nível cerca de 25% menor depois. A fonte não diz se é demanda ou mudança no que é contado; a página marca a linha em vez de comparar os dois lados.
- **A ocupação ao vivo começou em 3 de outubro de 2026.** O ranking precisa de alguns dias de retratos para fazer sentido e melhora a cada dia; a página avisa enquanto houver menos de 72 horas de dados.

## Como funciona

```
                 a cada 15 min (minutos 7, 22, 37, 52)
 API BikePoint ──► coleta (handler no estilo serverless, só biblioteca padrão) ──► bruto intocado (.json.gz)
                                                                                   uma release do GitHub por dia
                 todo dia (GitHub Actions)
 últimos 28 dias de retratos ─┐
 agregados das viagens (CSV)  ├─► PostgreSQL temporário ─► dbt build + testes ─► exportador ─► GitHub Pages
 registros das execuções ─────┘    (recriado do bruto)     + source freshness    (recusa se
                                                                                 faltar dado)
                 quando a TfL publica um arquivo de viagens (no PC)
 bucket da TfL ──► download por ETag ──► carga incremental ──► PostgreSQL ──► dbt ──► agregados pequenos (CSV no repo)
```

**Dois ritmos.** O GitHub Actions não guarda banco entre execuções e não comportaria 41 milhões de viagens. Por isso a parte pesada e rara (os arquivos de viagens, publicados com meses de atraso) roda no PC, e a parte leve e diária roda no Actions. O job diário recria o banco a partir do bruto toda vez, o que prova na prática que o pipeline é reprodutível.

| Camada | O que faz |
|---|---|
| **Coleta** (`src/bicicletas/coleta_api.py`) | Só biblioteca padrão do Python, escrita como handler no estilo serverless (`lambda_handler(event, context)`), para poder ir para um agendador gerenciado sem mudar. Três tentativas com espera crescente; resposta sem a forma de BikePoint (página HTML de erro, lista vazia, campo faltando) é execução com falha e nunca entra no bruto. Cada execução grava um registro (sucesso ou falha, quem disparou, número de estações, SHA-256): o GitHub apaga o histórico em 90 dias, o registro fica. |
| **Bruto** | Cada resposta guardada byte a byte (gzip com `mtime=0`: o mesmo conteúdo dá o mesmo hash), chaves no formato do S3 (`bruto/bikepoint/data=AAAA-MM-DD/...`), nunca sobrescrita. Um `.tar` diário determinístico com manifesto de hashes faz o job diário baixar 28 arquivos em vez de ~2.700. |
| **Arquivos de viagens** (`viagens_download.py`, `viagens_carga.py`) | Baixados por ETag com recibo (tamanho, SHA-256, data de publicação), num arquivo `.parcial` trocado só depois de conferido. Carregados **pelo nome da coluna**, nunca pela posição; coluna desconhecida, coluna faltando ou linha com número errado de campos recusa o arquivo. Uma transação por arquivo: apaga as linhas daquele arquivo, insere, registra a versão. Rodar duas vezes não duplica; arquivo republicado substitui a versão anterior; falha no meio deixa a versão anterior intacta. |
| **dbt** (`dbt/`) | `staging` (tipos, os dois formatos unificados) → `intermediario` → `marts` (ocupação por estação e hora, demanda perdida, ranking, fluxos, saúde): 17 modelos com 47 testes de dados e source freshness (retratos: aviso com 1 h, erro com 3 h). |
| **Página** (`site/`) | Exportada só depois que o `dbt build` passa; teste falhando mantém a página de ontem. Coleta atrasada não bloqueia a página: ela mostra a saúde em vermelho. |

## Qualidade dos dados: medir antes de decidir

| Achado | O que foi feito |
|---|---|
| **6 variantes de cabeçalho** nos arquivos de viagens desde 2022: colunas em ordens diferentes, um arquivo sem `EndStation Id`, quatro arquivos que passaram pelo Excel (sem aspas, datas como `14/08/2024`, estação `022165` escrita `22165`) | Leitura pelo nome da coluna; dois formatos de data; número de estação completado de volta para 6 dígitos (= `TerminalName` da API) |
| **0 viagens repetidas** em 148 arquivos, mesmo onde os nomes se sobrepõem num dia | Sem deduplicação; um teste `unique` protege |
| **Estações que mudaram de lugar**: local antigo marcado com sufixo (`200025444`, `300006-1`) e nome terminado em `_OLD`, 139.628 viagens (0,34%) | Mantidas como "local antigo", fora das análises por estação |
| **A hora repetida** no fim do horário de verão britânico: 3.129 viagens | Regra do PostgreSQL (segunda ocorrência, GMT), marcadas; duração vem da coluna de duração |
| **3 dias quase sem viagens** (10 e 11/09/2022, 05/08/2025) | Contados por mês (`dias_incompletos`) e mostrados no gráfico |
| **A API serve de cache**: retratos seguidos podem ser idênticos byte a byte; idade mediana do dado na coleta ~20 min | Ocupação medida no instante da coleta; idade do dado medida todo dia e mostrada |
| **Em 625 de 799 estações, bicicletas + vagas ≠ docas** (docas fora de serviço) | Vazia = `NbBikes = 0`, cheia = `NbEmptyDocks = 0`, nunca derivado de `NbDocks` |

## Como rodar

Requisitos: Python 3.14, Docker (PostgreSQL 16) e Git Bash no Windows.

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env                     # defina sua senha e a pasta dos dados
python -m bicicletas.bootstrap           # usuário e bancos no container PostgreSQL
python -m bicicletas.migracoes principal
python -m bicicletas.viagens_download    # ~6,5 GB de arquivos de viagens, fora do OneDrive
python -m bicicletas.viagens_carga       # 41 milhões de linhas; rodar de novo = nada a fazer
python -m bicicletas.dbt_rodar build --select tag:viagens
python -m bicicletas.agregados exportar && python -m bicicletas.agregados carregar
python -m bicicletas.retratos_carga --pasta <pasta com os retratos>
python -m bicicletas.dbt_rodar build --select tag:diario
python -m bicicletas.exportar_site
pytest                                   # 197 testes; pytest -m rede também usa a API real
```

## Testes

197 testes automáticos e mais um contra a API ao vivo:
- **Entradas hostis:** HTML no lugar de JSON, gzip truncado, coluna desconhecida no CSV, SQL injection em nomes, arquivo alterado depois do download, arquivo republicado e falha no meio de uma carga.
- **Scripts de shell** rodando contra um `gh` falso.
- **Teste de ponta a ponta:** vai do bruto ao dbt, aos agregados, ao dbt diário e aos dados da página, conferindo os números que saem do outro lado (45 minutos vazia × 2,5 retiradas por hora = 1,9 viagem perdida).

O CI roda tudo a cada push contra um PostgreSQL de verdade, e aviso vira erro.

## Limitações e próximos passos

- **A demanda perdida é uma estimativa conservadora.** As viagens passadas só aconteceram quando havia bicicleta, então a taxa usual já subestima a procura onde a estação costuma ficar vazia.
- **A ocupação tem resolução de 15 minutos**, e o cache da própria API soma uns 20 minutos de atraso.
- **Os arquivos de viagens chegam com meses de atraso.** O perfil de demanda é dos 12 meses publicados mais recentes, não da semana atual.
- **O cron do GitHub Actions atrasa e pode pular execuções.** Cada execução agendada é medida contra o seu horário. Medido em 04/10/2026: rodaram 5 das 96 janelas (todas com sucesso). O workflow agora também aceita chamadas de um agendador externo gratuito nos mesmos minutos, contadas como agendadas ([passo a passo](docs/COLETA_AGENDADA.md)); o cron do GitHub fica de reserva. Passo seguinte: um agendador gerenciado (Lambda + EventBridge), com o mesmo handler e as mesmas chaves do bruto.

## Fonte dos dados e licença

Powered by TfL Open Data. Contém dados da Transport for London, usados conforme os termos de dados de transporte da TfL (baseados na Open Government Licence v2.0). Mapa © colaboradores do OpenStreetMap. Este projeto não tem vínculo com a Transport for London nem é endossado por ela.
