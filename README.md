# London Cycle Hire Pipeline

> 🚧 **Under construction.** The first part, the live collector, is built and tested; the transformations, the results page and the full write-up are being built. [Leia em português](README.pt-BR.md).

A data pipeline for London's public bikes (TfL Santander Cycles). The operational problem is **rebalancing**: in the morning residential docking stations run empty and central ones fill up, and in the evening it is the other way round. An empty station is a trip that never happens; a full one is a rider who cannot return the bike.

The pipeline answers four questions:

1. Which stations run empty or full, and at what times?
2. How long does each station spend with no bikes (or no free docks) per day?
3. What are the origin → destination flows by hour and weekday?
4. Where should the operations team act first? (ranked by estimated lost demand)

## What exists today

- **Live collector** (`src/bicicletas/coleta_api.py`): every 15 minutes, GitHub Actions takes a snapshot of the TfL BikePoint API (≈800 stations). Each response is stored byte for byte, compressed, in a daily GitHub Release that works as a temporary data lake (keys follow the S3 layout `bruto/bikepoint/data=YYYY-MM-DD/...`). Every run also writes a run record (success or failure, trigger, station count, hash), which will be used to measure scheduler delay.
- **Daily package** (`src/bicicletas/pacote_diario.py`): the previous day's files bundled in a deterministic `.tar` with a hash manifest, verified before publishing.
- **Tests**: unit, integration (PostgreSQL) and shell-script tests, including hostile cases (API down, HTML instead of JSON, truncated files, attempts to overwrite raw data). CI runs them on every push against a real PostgreSQL.

Planning and decisions (in Portuguese): [docs/PLAN.md](docs/PLAN.md) and [docs/DECISOES.md](docs/DECISOES.md).

## Data source and licence

Powered by TfL Open Data. Contains data from Transport for London, used under the TfL transport data terms (based on the Open Government Licence v2.0). This project is not affiliated with or endorsed by Transport for London.
