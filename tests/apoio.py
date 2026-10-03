"""Funções de apoio usadas pelos testes e pelas fixtures."""

from collections.abc import Mapping

from bicicletas.banco import Conexao


def valor(con: Conexao, comando: str, parametros: Mapping[str, object] | None = None) -> object:
    """Primeira coluna da primeira linha de uma consulta."""
    resultado = con.execute(comando, parametros).fetchone()
    assert resultado is not None, f"consulta sem resultado: {comando}"
    return resultado[0]
