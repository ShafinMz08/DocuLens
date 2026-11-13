"""add pgvector embeddings

Revision ID: c7f2a91d4e05
Revises: b33ffc1b7a6d
Create Date: 2026-11-13 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'c7f2a91d4e05'
down_revision: Union[str, None] = 'b33ffc1b7a6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector must exist before the vector column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        "CREATE TYPE embeddingstatus AS ENUM "
        "('pending', 'processing', 'completed', 'failed')"
    )
    embedding_status_type = sa.Enum(
        'pending', 'processing', 'completed', 'failed',
        name='embeddingstatus', create_type=False,
    )
    op.add_column(
        'documents',
        sa.Column(
            'embedding_status',
            embedding_status_type,
            nullable=False,
            server_default='pending',
        )
    )
    op.add_column('documents', sa.Column('embedding_error', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('embedding_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('documents', sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('document_chunks', sa.Column('embedding', Vector(384), nullable=True))
    op.add_column('document_chunks', sa.Column('embedding_model', sa.String(length=255), nullable=True))
    op.create_index(
        'ix_document_chunks_embedding_hnsw',
        'document_chunks',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )


def downgrade() -> None:
    op.drop_index('ix_document_chunks_embedding_hnsw', table_name='document_chunks')
    op.drop_column('document_chunks', 'embedding_model')
    op.drop_column('document_chunks', 'embedding')
    op.drop_column('documents', 'embedded_at')
    op.drop_column('documents', 'embedding_started_at')
    op.drop_column('documents', 'embedding_error')
    op.drop_column('documents', 'embedding_status')
    op.execute("DROP TYPE embeddingstatus")
    op.execute("DROP EXTENSION IF EXISTS vector")
