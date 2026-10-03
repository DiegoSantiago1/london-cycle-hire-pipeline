"""Fixtures compartilhadas pelos testes.

Testes marcados com @pytest.mark.integracao precisam do Docker e do banco. Se o banco
não estiver acessível eles FALHAM com uma mensagem clara, em vez de serem pulados em
silêncio: um teste pulado sem ninguém ver é um teste que não existe.
Para rodar só os unitários: pytest -m "not integracao".

Os testes de banco usam o banco de TESTES (BICICLETAS_DB_NAME_TESTE), que é apagado e
recriado pelas migrações no início de cada execução. O banco principal não é tocado.
"""

from collections.abc import Iterator

import psycopg
import pytest
import sqlalchemy.exc
from alembic import command

from bicicletas.banco import Conexao, conectar
from bicicletas.config import ConfigBanco, ConfigError, carregar_config_banco
from bicicletas.migracoes import config_alembic

from .apoio import valor

SCHEMAS = ("bruto", "controle", "agregados")
SCHEMAS_DBT = ("staging", "intermediario", "marts", "dbt")


def falhar_sem_banco(erro: Exception) -> None:
    pytest.fail(
        f"Banco inacessível ({erro}). Docker Desktop aberto? Já rodou "
        "'python -m bicicletas.bootstrap'?",
        pytrace=False,
    )


@pytest.fixture(scope="session")
def config_banco() -> ConfigBanco:
    try:
        return carregar_config_banco()
    except ConfigError as erro:
        pytest.fail(f"Configuração do banco inválida: {erro}", pytrace=False)


@pytest.fixture(scope="session")
def banco_teste(config_banco: ConfigBanco) -> ConfigBanco:
    """Banco de testes recriado do zero pelas migrações.

    Sobe tudo, desce tudo (confere que não sobrou nada) e sobe de novo: cada execução
    dos testes também exercita os downgrades.
    """
    config = config_banco.do_banco_de_teste()
    assert config.nome != config_banco.nome  # trava extra: nunca recriar o principal
    alembic = config_alembic(config.url())
    try:
        # Os schemas do dbt (views sobre o bruto) impediriam o downgrade: saem antes.
        with conectar(config) as con:
            con.execute(f"DROP SCHEMA IF EXISTS {', '.join(SCHEMAS_DBT)} CASCADE")
        command.upgrade(alembic, "head")
        command.downgrade(alembic, "base")
        with conectar(config) as con:
            sobrou = valor(
                con,
                "SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%(s)s)",
                {"s": list(SCHEMAS)},
            )
        assert sobrou == 0, "downgrade base deixou schemas para trás"
        command.upgrade(alembic, "head")
    except (psycopg.OperationalError, sqlalchemy.exc.OperationalError) as erro:
        # O Alembic passa pelo SQLAlchemy, que embrulha o erro do psycopg no dele.
        falhar_sem_banco(erro)
    return config


@pytest.fixture
def bd(banco_teste: ConfigBanco) -> Iterator[Conexao]:
    """Conexão ao banco de testes dentro de uma transação desfeita no fim do teste."""
    con = conectar(banco_teste)
    con.execute("SELECT 1")  # abre a transação: blocos internos viram savepoints
    try:
        yield con
    finally:
        con.rollback()
        con.close()
