"""bruto das viagens e controle dos arquivos carregados

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03

- controle.arquivos_viagens: uma linha por arquivo da TfL carregado, com a versão
  (ETag, SHA-256) e o cabeçalho que veio. É o que torna a carga incremental: arquivo com
  o mesmo SHA-256 não é carregado de novo; SHA-256 diferente (republicado) é recarregado.
- bruto.viagens: as viagens como vieram, tudo em texto, com o arquivo e a linha de origem.
  As duas gerações de colunas da TfL (antes e depois de set/2022) caem nas mesmas colunas
  pelo NOME da coluna, nunca pela posição. Tipar, padronizar e deduplicar é papel do dbt.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE controle.arquivos_viagens (
            arquivo       text PRIMARY KEY CHECK (arquivo ~ '^[A-Za-z0-9._-]+\\.csv$'),
            etag          text        NOT NULL CHECK (etag <> ''),
            bytes         bigint      NOT NULL CHECK (bytes > 0),
            sha256        text        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            publicado_em  timestamptz NOT NULL,
            vocabulario   text        NOT NULL CHECK (vocabulario IN ('antigo', 'novo')),
            cabecalho     text        NOT NULL,
            linhas        integer     NOT NULL CHECK (linhas >= 0),
            carregado_em  timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE controle.arquivos_viagens IS
            'Arquivos de viagens da TfL já carregados em bruto.viagens, com a versão (ETag, SHA-256).';
        COMMENT ON COLUMN controle.arquivos_viagens.publicado_em IS
            'LastModified do S3 da TfL: quando a TfL publicou esta versão do arquivo.';

        CREATE TABLE bruto.viagens (
            arquivo                text    NOT NULL
                REFERENCES controle.arquivos_viagens (arquivo) ON DELETE CASCADE,
            linha                  integer NOT NULL CHECK (linha >= 2),
            numero                 text,
            inicio                 text,
            fim                    text,
            estacao_inicio_numero  text,
            estacao_inicio_nome    text,
            estacao_fim_numero     text,
            estacao_fim_nome       text,
            bicicleta              text,
            modelo                 text,
            duracao_s              text,
            duracao_texto          text,
            duracao_ms             text,
            PRIMARY KEY (arquivo, linha)
        );
        COMMENT ON TABLE bruto.viagens IS
            'Viagens como vieram nos CSVs da TfL (texto), com arquivo e linha de origem.';
        COMMENT ON COLUMN bruto.viagens.linha IS
            'Número da linha no CSV (o cabeçalho é a linha 1).';
        COMMENT ON COLUMN bruto.viagens.duracao_s IS
            'Só no formato antigo (até set/2022): coluna Duration, em segundos.';
        COMMENT ON COLUMN bruto.viagens.duracao_texto IS
            'Só no formato novo: coluna Total duration, ex.: 2h 18m 16s.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE bruto.viagens;
        DROP TABLE controle.arquivos_viagens;
        """
    )
