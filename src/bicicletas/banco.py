"""Acesso ao banco: conexão do psycopg."""

from __future__ import annotations

import psycopg
from psycopg.rows import TupleRow

from bicicletas.config import ConfigBanco

type Conexao = psycopg.Connection[TupleRow]


def conectar(config: ConfigBanco) -> Conexao:
    """Conecta com o usuário e o banco da config."""
    return psycopg.connect(
        host=config.host,
        port=config.porta,
        dbname=config.nome,
        user=config.usuario,
        password=config.senha,
        connect_timeout=5,
    )
