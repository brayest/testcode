"""empty message

Revision ID: 128e82ac2885
Revises: 2d8002f6f74e
Create Date: 2019-04-11 10:19:05.585492

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "128e82ac2885"
down_revision = "2d8002f6f74e"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "teachers",
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default="False"),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("teachers", "is_approved")
    # ### end Alembic commands ###
