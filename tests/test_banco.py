"""Testes de integração do banco: schemas, fuso, privilégios do usuário."""

import pytest

from bicicletas.banco import Conexao

from .apoio import valor
from .conftest import SCHEMAS

pytestmark = pytest.mark.integracao


def test_schemas_criados_pelas_migracoes(bd: Conexao) -> None:
    existentes = {
        linha[0]
        for linha in bd.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%(s)s)", {"s": list(SCHEMAS)}
        )
    }
    assert existentes == set(SCHEMAS)


def test_fuso_da_sessao_e_londres(bd: Conexao) -> None:
    assert valor(bd, "SHOW timezone") == "Europe/London"


def test_usuario_do_projeto_sem_privilegios_extras(bd: Conexao) -> None:
    linha = bd.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert linha == (False, False, False, False)


def test_public_nao_conecta_no_banco(bd: Conexao) -> None:
    # REVOKE ALL ... FROM PUBLIC no bootstrap: outro usuário do container não entra aqui.
    assert (
        valor(bd, "SELECT has_database_privilege('public', current_database(), 'CONNECT')") is False
    )


def test_usuario_nao_conecta_em_banco_de_outro_projeto(bd: Conexao) -> None:
    # O container é compartilhado: o usuário deste projeto não deve enxergar o Projeto 3.
    tem = valor(
        bd,
        "SELECT coalesce(bool_or(has_database_privilege(datname, 'CONNECT')), false) "
        "FROM pg_database WHERE datname IN ('retail', 'almoxarifado')",
    )
    assert tem is False
