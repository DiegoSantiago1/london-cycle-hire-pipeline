"""schemas bruto, controle e agregados

Revision ID: 0001
Revises:
Create Date: 2026-10-03

Os schemas que o Python preenche. Os de transformação (staging, intermediario,
marts) são criados pelo dbt, que é dono deles.
- bruto: os dados como vieram da TfL (texto, sem regras), com a origem de cada linha;
- controle: o que já foi carregado e o histórico das execuções (base da carga
  incremental e da saúde do pipeline);
- agregados: resumos das viagens trazidos do repositório, para o job diário, que não
  tem as viagens completas.
As tabelas entram nas migrações de cada fase.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA bruto;
        COMMENT ON SCHEMA bruto IS
            'Dados da TfL como vieram (texto, sem regras), com o arquivo de origem de cada linha.';
        CREATE SCHEMA controle;
        COMMENT ON SCHEMA controle IS
            'Arquivos já carregados e histórico das execuções: base da carga incremental.';
        CREATE SCHEMA agregados;
        COMMENT ON SCHEMA agregados IS
            'Resumos das viagens trazidos do repositório, usados pelo job diário.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP SCHEMA agregados;
        DROP SCHEMA controle;
        DROP SCHEMA bruto;
        """
    )
