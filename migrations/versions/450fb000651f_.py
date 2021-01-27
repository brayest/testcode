"""empty message

Revision ID: 450fb000651f
Revises: bcbaf7a9f0a8
Create Date: 2019-01-18 16:16:19.886416

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '450fb000651f'
down_revision = 'bcbaf7a9f0a8'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('lessons', 'dropoff_place_id',
                    existing_type=sa.INTEGER(),
                    nullable=True)
    op.alter_column('lessons', 'meetup_place_id',
                    existing_type=sa.INTEGER(),
                    nullable=True)
    op.add_column('places', sa.Column(
        'times_used', sa.Integer(), nullable=True))
    op.add_column('places', sa.Column(
        'used_as', sa.Integer(), nullable=False))
    op.drop_column('places', 'used_as_meetup')
    op.drop_column('places', 'used_as_dropoff')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('places', sa.Column('used_as_dropoff',
                                      sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('places', sa.Column('used_as_meetup',
                                      sa.INTEGER(), autoincrement=False, nullable=True))
    op.drop_column('places', 'used_as')
    op.drop_column('places', 'times_used')
    op.alter_column('lessons', 'meetup_place_id',
                    existing_type=sa.INTEGER(),
                    nullable=False)
    op.alter_column('lessons', 'dropoff_place_id',
                    existing_type=sa.INTEGER(),
                    nullable=False)
    # ### end Alembic commands ###
