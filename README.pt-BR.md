# London Cycle Hire Pipeline

> 🚧 **Em construção.** A primeira parte, a coleta ao vivo, está pronta e testada; as transformações, a página de resultados e a documentação completa estão sendo construídas. [Read in English](README.md).

Pipeline de dados das bicicletas públicas de Londres (TfL Santander Cycles). O problema operacional é o **rebalanceamento**: de manhã as estações residenciais esvaziam e as do centro lotam; à tarde, o inverso. Estação vazia é viagem que não acontece; estação cheia é usuário que não consegue devolver a bicicleta.

O pipeline responde quatro perguntas:

1. Quais estações ficam vazias ou cheias, e em que horários?
2. Quanto tempo por dia cada estação passa sem bicicleta (ou sem vaga)?
3. Quais são os fluxos origem → destino por hora e dia da semana?
4. Onde a operação deveria agir primeiro? (ranking por demanda perdida estimada)

## O que já existe

- **Coleta ao vivo** (`src/bicicletas/coleta_api.py`): a cada 15 minutos, o GitHub Actions tira um retrato da API BikePoint da TfL (~800 estações). Cada resposta é guardada byte a byte, comprimida, numa release diária do GitHub, que funciona como data lake provisório (chaves no formato do S3: `bruto/bikepoint/data=AAAA-MM-DD/...`). Cada execução também grava um registro (sucesso ou falha, quem disparou, número de estações, hash), que vai servir para medir o atraso do agendador.
- **Pacote diário** (`src/bicicletas/pacote_diario.py`): os arquivos do dia anterior num `.tar` determinístico com manifesto de hashes, conferido antes de publicar.
- **Testes**: unitários, de integração (PostgreSQL) e dos scripts de shell, inclusive casos hostis (API fora do ar, HTML no lugar de JSON, arquivo truncado, tentativa de sobrescrever o bruto). O CI roda tudo a cada push contra um PostgreSQL de verdade.

Planejamento e decisões: [docs/PLAN.md](docs/PLAN.md) e [docs/DECISOES.md](docs/DECISOES.md).

## Fonte dos dados e licença

Powered by TfL Open Data. Contém dados da Transport for London, usados conforme os termos de dados de transporte da TfL (baseados na Open Government Licence v2.0). Este projeto não tem vínculo com a Transport for London nem é endossado por ela.
