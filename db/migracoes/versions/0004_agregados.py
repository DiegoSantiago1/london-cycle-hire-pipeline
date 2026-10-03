"""tabelas dos agregados das viagens

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03

Os agregados são calculados no PC a partir das 41 milhões de viagens (dbt, tag
"viagens"), exportados para dados/agregados/*.csv no repositório e carregados aqui. O
job diário do GitHub Actions não tem as viagens: usa estas tabelas. O PC também lê
daqui (e não direto dos marts), para os dois ambientes seguirem o mesmo caminho.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agregados.demanda_estacao_hora (
            terminal          text    NOT NULL CHECK (terminal ~ '^[0-9]{6}$'),
            dia_semana        integer NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
            hora              integer NOT NULL CHECK (hora BETWEEN 0 AND 23),
            retiradas_media   numeric NOT NULL CHECK (retiradas_media >= 0),
            devolucoes_media  numeric NOT NULL CHECK (devolucoes_media >= 0),
            PRIMARY KEY (terminal, dia_semana, hora)
        );
        CREATE TABLE agregados.fluxos_hora (
            hora           integer NOT NULL CHECK (hora BETWEEN 0 AND 23),
            posicao        integer NOT NULL CHECK (posicao BETWEEN 1 AND 20),
            origem         text    NOT NULL CHECK (origem ~ '^[0-9]{6}$'),
            destino        text    NOT NULL CHECK (destino ~ '^[0-9]{6}$'),
            viagens_media  numeric NOT NULL CHECK (viagens_media > 0),
            PRIMARY KEY (hora, posicao),
            CHECK (origem <> destino)
        );
        CREATE TABLE agregados.viagens_mes (
            mes                  date    PRIMARY KEY,
            viagens              integer NOT NULL CHECK (viagens > 0),
            duracao_mediana_min  numeric NOT NULL CHECK (duracao_mediana_min > 0),
            pct_eletricas        numeric CHECK (pct_eletricas BETWEEN 0 AND 1)
        );
        CREATE TABLE agregados.estacoes_viagens (
            terminal        text    PRIMARY KEY CHECK (terminal ~ '^[0-9]{6}$'),
            nome            text    NOT NULL,
            retiradas_12m   integer NOT NULL CHECK (retiradas_12m >= 0),
            devolucoes_12m  integer NOT NULL CHECK (devolucoes_12m >= 0)
        );
        CREATE TABLE agregados.metadados (
            chave  text PRIMARY KEY,
            valor  text NOT NULL
        );
        COMMENT ON TABLE agregados.metadados IS
            'Sobre a última exportação: janela, total de viagens, arquivos, publicação mais recente.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE agregados.metadados;
        DROP TABLE agregados.estacoes_viagens;
        DROP TABLE agregados.viagens_mes;
        DROP TABLE agregados.fluxos_hora;
        DROP TABLE agregados.demanda_estacao_hora;
        """
    )
