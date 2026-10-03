"""Testes da configuração: valores válidos, ausentes e hostis."""

import pytest

from bicicletas.config import ConfigError, carregar_config_banco

ENV_VALIDO = {
    "BICICLETAS_DB_HOST": "127.0.0.1",
    "BICICLETAS_DB_PORT": "5432",
    "BICICLETAS_DB_NAME": "bicicletas",
    "BICICLETAS_DB_NAME_TESTE": "bicicletas_teste",
    "BICICLETAS_DB_USER": "bicicletas",
    "BICICLETAS_DB_PASSWORD": "senha_de_teste",
}


def test_config_valida() -> None:
    config = carregar_config_banco(ENV_VALIDO)
    assert config.porta == 5432
    assert config.do_banco_de_teste().nome == "bicicletas_teste"


def test_senha_nao_aparece_no_repr() -> None:
    assert "senha_de_teste" not in repr(carregar_config_banco(ENV_VALIDO))


def test_url_cita_caracteres_especiais_da_senha() -> None:
    config = carregar_config_banco({**ENV_VALIDO, "BICICLETAS_DB_PASSWORD": "a@b/c:d"})
    assert config.url().password == "a@b/c:d"


@pytest.mark.parametrize("variavel", sorted(ENV_VALIDO))
def test_variavel_ausente(variavel: str) -> None:
    env = {k: v for k, v in ENV_VALIDO.items() if k != variavel}
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env)


@pytest.mark.parametrize("variavel", sorted(ENV_VALIDO))
def test_variavel_em_branco(variavel: str) -> None:
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco({**ENV_VALIDO, variavel: "   "})


@pytest.mark.parametrize("porta", ["abc", "0", "65536", "-1", "54.32"])
def test_porta_invalida(porta: str) -> None:
    with pytest.raises(ConfigError, match="BICICLETAS_DB_PORT"):
        carregar_config_banco({**ENV_VALIDO, "BICICLETAS_DB_PORT": porta})


@pytest.mark.parametrize(
    "nome", ["Bicicletas", "1banco", "banco-x", "banco; DROP DATABASE x", "a" * 64, "ção"]
)
@pytest.mark.parametrize(
    "variavel", ["BICICLETAS_DB_NAME", "BICICLETAS_DB_NAME_TESTE", "BICICLETAS_DB_USER"]
)
def test_identificador_hostil(variavel: str, nome: str) -> None:
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco({**ENV_VALIDO, variavel: nome})


def test_banco_de_teste_igual_ao_principal_e_recusado() -> None:
    # Os testes apagam o banco de testes: se fosse o principal, apagariam os dados.
    with pytest.raises(ConfigError, match="não pode ser igual"):
        carregar_config_banco({**ENV_VALIDO, "BICICLETAS_DB_NAME_TESTE": "bicicletas"})
