"""dias incompletos na tendência mensal

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03

Medido em 03/10/2026: três dias quase sem viagens nos arquivos da TfL (10 e 11/09/2022,
na troca do sistema de dados da TfL, com 4 e 7 viagens; 05/08/2025, com 188), contra
20 a 35 mil num dia normal. São buracos nos dados, não dias sem demanda. A tendência
mensal passa a dizer quantos dias de cada mês estão incompletos.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agregados.viagens_mes
            ADD COLUMN dias_incompletos integer NOT NULL DEFAULT 0 CHECK (dias_incompletos >= 0);
        COMMENT ON COLUMN agregados.viagens_mes.dias_incompletos IS
            'Dias do mês com menos de 2.000 viagens nos arquivos (buraco nos dados da TfL).';
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agregados.viagens_mes DROP COLUMN dias_incompletos;")
