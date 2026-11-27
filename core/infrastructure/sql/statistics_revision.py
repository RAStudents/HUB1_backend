from sqlalchemy import inspect, text


def install_statistics_revision(connection):
    """Invalidate snapshots in the same transaction as their source data."""
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(772018115)"))
        installed = connection.execute(text("""
            SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'samples'::regclass AND tgname = 'hub_statistics_samples_insert'
        """)).first()
    elif dialect == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        installed = connection.execute(text("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'trigger' AND name = 'hub_statistics_samples_insert'
        """)).first()
    else:
        raise RuntimeError(f"Statistics revisions do not support {dialect}")
    if installed:
        return

    if dialect == "postgresql":
        connection.execute(text("LOCK TABLE samples, classes, sample_geometries IN SHARE ROW EXCLUSIVE MODE"))
    if "statistics_revision" not in {column["name"] for column in inspect(connection).get_columns("datasets")}:
        connection.execute(text("ALTER TABLE datasets ADD COLUMN statistics_revision BIGINT NOT NULL DEFAULT 0"))

    for table, columns in (
        ("samples", ("dataset_id", "split", "status", "is_labeled", "label_key")),
        ("classes", ("dataset_id", "class_index", "name")),
        ("sample_geometries", ("sample_id", "geometry_json")),
    ):
        for operation, references in (("INSERT", ("NEW",)), ("UPDATE", ("OLD", "NEW")), ("DELETE", ("OLD",))):
            name = f"hub_statistics_{table}_{operation.lower()}"
            owner_ids = [
                f"(SELECT dataset_id FROM samples WHERE id = {ref}.sample_id)"
                if table == "sample_geometries" else f"{ref}.dataset_id"
                for ref in references
            ]
            body = f"""
                UPDATE datasets SET statistics_revision = statistics_revision + 1
                WHERE id IN ({', '.join(owner_ids)});
            """
            when = ""
            if operation == "UPDATE":
                comparison = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
                changes = " OR ".join(f"OLD.{column} {comparison} NEW.{column}" for column in columns)
                when = f"WHEN ({changes})"

            if dialect == "sqlite":
                connection.execute(text(f"""
                    CREATE TRIGGER {name} AFTER {operation} ON {table} FOR EACH ROW {when}
                    BEGIN {body} END
                """))
            else:
                connection.execute(text(f"""
                    CREATE FUNCTION {name}() RETURNS trigger AS $$
                    BEGIN {body} RETURN NULL; END; $$ LANGUAGE plpgsql
                """))
                connection.execute(text(f"""
                    CREATE TRIGGER {name} AFTER {operation} ON {table} FOR EACH ROW {when}
                    EXECUTE FUNCTION {name}()
                """))
