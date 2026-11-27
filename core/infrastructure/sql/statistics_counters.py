"""Incremental, persistent dataset statistics for SQLite and PostgreSQL.

All counters change in the same transaction as their source rows, including
bulk import, rollback, and cascading deletion. Reads never rebuild statistics.
"""
from sqlalchemy import text


def install_statistics_counters(connection):
    dialect = connection.dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError(f"Statistics counters do not support {dialect}")
    if connection.execute(text("SELECT version FROM statistics_migrations WHERE version = 1")).first():
        return

    def sample_delta(ref, delta):
        if delta < 0:
            return f"""UPDATE dataset_sample_counts SET count = count - 1
                WHERE dataset_id = {ref}.dataset_id AND split = {ref}.split
                  AND is_labeled = {ref}.is_labeled;"""
        return f"""INSERT INTO dataset_sample_counts (dataset_id, split, is_labeled, count)
            VALUES ({ref}.dataset_id, {ref}.split, {ref}.is_labeled, 1)
            ON CONFLICT (dataset_id, split, is_labeled)
            DO UPDATE SET count = dataset_sample_counts.count + 1;"""

    def annotation_delta(ref, delta):
        if delta < 0:
            return f"""UPDATE dataset_class_counts SET count = count - 1
                WHERE dataset_id = (SELECT dataset_id FROM samples WHERE id = {ref}.sample_id)
                  AND class_id = {ref}.class_id;
                UPDATE sample_object_counts SET count = count - 1 WHERE sample_id = {ref}.sample_id;"""
        return f"""INSERT INTO dataset_class_counts (dataset_id, class_id, count)
            SELECT dataset_id, {ref}.class_id, 1 FROM samples WHERE id = {ref}.sample_id
            ON CONFLICT (dataset_id, class_id)
            DO UPDATE SET count = dataset_class_counts.count + 1;
            UPDATE sample_object_counts SET count = count + 1 WHERE sample_id = {ref}.sample_id;"""

    triggers = [
        ("samples_insert", "AFTER", "INSERT", "samples", "", sample_delta("NEW", 1) +
         " INSERT INTO sample_object_counts (sample_id, count) VALUES (NEW.id, 0);"),
        ("samples_delete", "BEFORE", "DELETE", "samples", "", sample_delta("OLD", -1) +
         " DELETE FROM annotations WHERE sample_id = OLD.id;"),
        ("samples_update", "AFTER", "UPDATE", "samples",
         "OLD.dataset_id <> NEW.dataset_id OR OLD.split <> NEW.split OR OLD.is_labeled <> NEW.is_labeled",
         sample_delta("OLD", -1) + sample_delta("NEW", 1)),
        ("samples_move", "AFTER", "UPDATE", "samples", "OLD.dataset_id <> NEW.dataset_id",
         """UPDATE dataset_class_counts SET count = count - (
             SELECT COUNT(*) FROM annotations WHERE sample_id = OLD.id
               AND class_id = dataset_class_counts.class_id
         ) WHERE dataset_id = OLD.dataset_id;
         INSERT INTO dataset_class_counts (dataset_id, class_id, count)
         SELECT NEW.dataset_id, class_id, COUNT(*) FROM annotations WHERE sample_id = NEW.id GROUP BY class_id
         ON CONFLICT (dataset_id, class_id) DO UPDATE SET count = dataset_class_counts.count + excluded.count;"""),
        ("annotations_insert", "AFTER", "INSERT", "annotations", "", annotation_delta("NEW", 1)),
        ("annotations_delete", "AFTER", "DELETE", "annotations", "", annotation_delta("OLD", -1)),
        ("annotations_update", "AFTER", "UPDATE", "annotations",
         "OLD.sample_id <> NEW.sample_id OR OLD.class_id <> NEW.class_id",
         annotation_delta("OLD", -1) + annotation_delta("NEW", 1)),
    ]
    # Serialize startup migration against concurrent writes on PostgreSQL.
    if dialect == "postgresql":
        connection.execute(text("LOCK TABLE samples, annotations IN SHARE ROW EXCLUSIVE MODE"))
        if connection.execute(text("SELECT version FROM statistics_migrations WHERE version = 1")).first():
            return
    # One backfill for existing datasets. Subsequent startups return above.
    for table in ("dataset_sample_counts", "dataset_class_counts", "sample_object_counts"):
        connection.execute(text(f"DELETE FROM {table}"))
    connection.execute(text("""INSERT INTO dataset_sample_counts
        SELECT dataset_id, split, is_labeled, COUNT(*) FROM samples
        GROUP BY dataset_id, split, is_labeled"""))
    connection.execute(text("""INSERT INTO dataset_class_counts
        SELECT s.dataset_id, a.class_id, COUNT(*) FROM annotations a
        JOIN samples s ON s.id = a.sample_id GROUP BY s.dataset_id, a.class_id"""))
    connection.execute(text("""INSERT INTO sample_object_counts
        SELECT s.id, COUNT(a.id) FROM samples s LEFT JOIN annotations a ON a.sample_id = s.id GROUP BY s.id"""))
    for name, timing, operation, table, condition, body in triggers:
        name = "hub_stats_" + name
        when = f"WHEN ({condition})" if condition else ""
        if dialect == "sqlite":
            connection.execute(text(f"CREATE TRIGGER {name} {timing} {operation} ON {table} FOR EACH ROW {when} BEGIN {body} END"))
        else:
            returned = "OLD" if operation == "DELETE" else "NEW"
            connection.execute(text(f"""CREATE OR REPLACE FUNCTION {name}() RETURNS trigger AS $$
                BEGIN {body} RETURN {returned}; END; $$ LANGUAGE plpgsql"""))
            connection.execute(text(f"CREATE TRIGGER {name} {timing} {operation} ON {table} FOR EACH ROW {when} EXECUTE FUNCTION {name}()"))
    connection.execute(text("INSERT INTO statistics_migrations (version) VALUES (1)"))
