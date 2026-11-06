"""drop search

api.search (the header's search box) and api.search_athletes (head-to-head) are no
longer called: the site fetches api.search_index once and searches in the browser
(ajr-web lib/search-index.ts). Each call scanned every athlete with a LIKE per word.

Revision ID: c8e2a6f4b159
Revises: b5d1f7a3e940
Create Date: 2026-11-12 13:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e2a6f4b159"
down_revision: Union[str, Sequence[str], None] = "b5d1f7a3e940"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def load_migration(name: str):
    """An earlier migration's module, to restore its functions."""
    import importlib.util
    from pathlib import Path

    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("drop function api.search(text)")
    op.execute("drop function api.search_athletes(text, text, integer)")


def downgrade() -> None:
    """Downgrade schema."""
    load_migration("6b4d2f8e1a97_search").upgrade()
    load_migration("d2a71c5e94b3_search_athletes").upgrade()
