"""Roda o dbt com o .env carregado e o profiles.yml do projeto.

Uso (os argumentos vão direto para o dbt):
    python -m bicicletas.dbt_rodar build --select tag:diario
    python -m bicicletas.dbt_rodar source freshness
    python -m bicicletas.dbt_rodar build --target teste

O dbt lê as credenciais por env_var() no profiles.yml; quem carrega o .env é este
módulo, para não precisar exportar variáveis à mão no terminal.
"""

from __future__ import annotations

import os
import sys

from bicicletas.config import RAIZ_PROJETO, carregar_env

PASTA_DBT = RAIZ_PROJETO / "dbt"


def rodar(argumentos: list[str]) -> int:
    from dbt.cli.main import dbtRunner

    carregar_env()
    os.environ.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    resultado = dbtRunner().invoke(
        [*argumentos, "--project-dir", str(PASTA_DBT), "--profiles-dir", str(PASTA_DBT)]
    )
    if resultado.exception is not None:
        print(f"Erro no dbt: {resultado.exception}", file=sys.stderr)
        return 2
    return 0 if resultado.success else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    return rodar(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
