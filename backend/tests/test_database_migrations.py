from sqlalchemy import create_engine, inspect, text

from database import ensure_schema_upgrades


LEGACY_DOCUMENTS_DDL = """
CREATE TABLE documents (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    filename VARCHAR NOT NULL,
    stored_path VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL,
    summary_json TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    index_path VARCHAR,
    created_at DATETIME
)
"""


def column_names(engine):
    return {column["name"] for column in inspect(engine).get_columns("documents")}


class TestEnsureSchemaUpgrades:

    def test_adds_summary_column_to_legacy_database(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

        with engine.begin() as connection:
            connection.execute(text(LEGACY_DOCUMENTS_DDL))

        ensure_schema_upgrades(engine)

        assert "summary" in column_names(engine)

        # Existing rows survive the migration and default to NULL.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents (id, user_id, filename, stored_path,"
                    " source_type, summary_json, chunk_count)"
                    " VALUES ('d1', 'u1', 'a.pdf', 'x', 'pdf', '{}', 1)"
                )
            )
            stored = connection.execute(
                text("SELECT summary FROM documents WHERE id = 'd1'")
            ).scalar()

        assert stored is None

    def test_is_idempotent(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

        with engine.begin() as connection:
            connection.execute(text(LEGACY_DOCUMENTS_DDL))

        ensure_schema_upgrades(engine)
        ensure_schema_upgrades(engine)  # must not raise on a second run

        assert "summary" in column_names(engine)

    def test_noop_when_table_missing(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")

        ensure_schema_upgrades(engine)  # must not create or crash

        assert "documents" not in inspect(engine).get_table_names()
