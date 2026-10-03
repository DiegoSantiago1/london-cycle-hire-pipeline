"""bruto dos retratos da API e das execuções da coleta

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03

- controle.arquivos_retratos: cada arquivo do bruto ao vivo já carregado (retrato ou
  registro de execução), com o SHA-256. Mesmo arquivo com o mesmo hash não é carregado
  de novo; o bruto é imutável, então hash diferente para o mesmo nome é erro.
- bruto.retratos: uma linha por estação por retrato, com os campos da API como texto.
  O "modified" de NbBikes é guardado porque a API serve de cache (D29): é ele que diz
  quando o dado da estação mudou de verdade.
- bruto.execucoes_coleta: o registro de cada execução da coleta (sucesso ou falha).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE controle.arquivos_retratos (
            arquivo       text PRIMARY KEY
                CHECK (arquivo ~ '^(bikepoint_\\d{4}-\\d{2}-\\d{2}T\\d{2}-\\d{2}-\\d{2}Z\\.json\\.gz|execucao_\\d{4}-\\d{2}-\\d{2}T\\d{2}-\\d{2}-\\d{2}Z\\.json)$'),
            tipo          text        NOT NULL CHECK (tipo IN ('retrato', 'execucao')),
            coletado_em   timestamptz NOT NULL,
            sha256        text        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            linhas        integer     NOT NULL CHECK (linhas >= 0),
            carregado_em  timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE controle.arquivos_retratos IS
            'Arquivos do bruto ao vivo (retratos e registros de execução) já carregados.';

        CREATE TABLE bruto.retratos (
            arquivo            text NOT NULL
                REFERENCES controle.arquivos_retratos (arquivo) ON DELETE CASCADE,
            coletado_em        timestamptz NOT NULL,
            estacao_id         text NOT NULL,
            nome               text,
            lat                text,
            lon                text,
            terminal           text,
            instalada          text,
            bloqueada          text,
            temporaria         text,
            data_instalacao    text,
            data_remocao       text,
            bicicletas         text,
            vagas_livres       text,
            docas              text,
            classicas          text,
            eletricas          text,
            atualizado_em      text,
            PRIMARY KEY (arquivo, estacao_id)
        );
        COMMENT ON TABLE bruto.retratos IS
            'Uma linha por estação por retrato da API BikePoint, campos como vieram (texto).';
        COMMENT ON COLUMN bruto.retratos.atualizado_em IS
            'Campo "modified" de NbBikes na API: quando a contagem da estação foi atualizada.';
        CREATE INDEX retratos_coletado_em ON bruto.retratos (coletado_em);

        CREATE TABLE bruto.execucoes_coleta (
            arquivo            text PRIMARY KEY
                REFERENCES controle.arquivos_retratos (arquivo) ON DELETE CASCADE,
            iniciado_em        text,
            terminado_em       text,
            status             text,
            origem             text,
            evento             text,
            id_execucao        text,
            tentativa_execucao text,
            chave_retrato      text,
            estacoes           text,
            bytes_brutos       text,
            bytes_comprimidos  text,
            sha256             text,
            erro               text
        );
        COMMENT ON TABLE bruto.execucoes_coleta IS
            'Registro de cada execução da coleta ao vivo (sucesso ou falha), como veio.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE bruto.execucoes_coleta;
        DROP TABLE bruto.retratos;
        DROP TABLE controle.arquivos_retratos;
        """
    )
