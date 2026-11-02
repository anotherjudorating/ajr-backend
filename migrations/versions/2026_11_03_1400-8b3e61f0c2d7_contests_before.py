"""contests before

api.competition_results: `debut` becomes `contests_before`, the athlete's rated
contests before their first one at this tournament. A debut is 0; but a few
contests are not enough either: the score of an athlete the rating knows little
about starts low and leaps, so the site counts a tournament's biggest gains only
among athletes with 10 contests or more before it.

Revision ID: 8b3e61f0c2d7
Revises: 5d1c2b7e9a40
Create Date: 2026-11-03 14:00:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b3e61f0c2d7"
down_revision: Union[str, Sequence[str], None] = "5d1c2b7e9a40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESULTS = "api.competition_results(integer)"


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous_competition_results() -> str:
    return load_migration("5d1c2b7e9a40_country").competition_results()


def competition_results() -> str:
    sql = (
        previous_competition_results()
        .replace("    debut boolean\n)", "    contests_before integer\n)")
        .replace(
            "           not exists (select from ajr.rating_change p\n"
            "                       where p.athlete_id = b.athlete_id and p.seq < b.first_seq)\n",
            "           (select count(*)::integer from ajr.rating_change p\n"
            "            where p.athlete_id = b.athlete_id and p.seq < b.first_seq)\n",
        )
    )
    assert "debut" not in sql and "count(*)::integer from ajr.rating_change p" in sql
    return sql


def replace(sql: str) -> None:
    op.execute(f"drop function {RESULTS}")  # its columns change
    op.execute(sql)
    op.execute(f"revoke execute on function {RESULTS} from public")
    op.execute(f"grant execute on function {RESULTS} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    replace(competition_results())


def downgrade() -> None:
    """Downgrade schema."""
    replace(previous_competition_results())
