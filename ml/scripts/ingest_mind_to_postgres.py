import os
import sys
import csv
import io
import time
from collections import defaultdict

from dotenv import load_dotenv
import psycopg2
from tqdm import tqdm

EXTRACT_DIR = os.path.join("ml", "data", "raw", "mind", "large", "extracted")
SPLITS = ["train", "dev", "test"]

BATCH_SIZE = 10000


def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_conn():
    return psycopg2.connect(
        host=get_env("DB_HOST"),
        port=get_env("DB_PORT"),
        dbname=get_env("DB_NAME"),
        user=get_env("DB_USER"),
        password=get_env("DB_PASSWORD"),
    )


def init_tables(conn) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS items (
        news_id TEXT PRIMARY KEY,
        category TEXT,
        subcategory TEXT,
        title TEXT,
        abstract TEXT,
        url TEXT,
        title_entities JSONB,
        abstract_entities JSONB
    );

    CREATE TABLE IF NOT EXISTS sessions (
        impression_id TEXT,
        user_id TEXT,
        time TEXT,
        split TEXT,
        PRIMARY KEY (split, impression_id)
    );

    CREATE TABLE IF NOT EXISTS impressions (
        impression_id TEXT,
        news_id TEXT,
        position INTEGER,
        clicked BOOLEAN,
        split TEXT,
        PRIMARY KEY (split, impression_id, news_id, position)
    );

    CREATE TABLE IF NOT EXISTS user_history (
        impression_id TEXT,
        news_id TEXT,
        position INTEGER,
        split TEXT,
        PRIMARY KEY (split, impression_id, news_id, position)
    );

    CREATE TABLE IF NOT EXISTS stg_items (
        news_id TEXT,
        category TEXT,
        subcategory TEXT,
        title TEXT,
        abstract TEXT,
        url TEXT,
        title_entities TEXT,
        abstract_entities TEXT
    );

    CREATE TABLE IF NOT EXISTS stg_sessions (
        impression_id TEXT,
        user_id TEXT,
        time TEXT,
        split TEXT
    );

    CREATE TABLE IF NOT EXISTS stg_impressions (
        impression_id TEXT,
        news_id TEXT,
        position INTEGER,
        clicked BOOLEAN,
        split TEXT
    );

    CREATE TABLE IF NOT EXISTS stg_user_history (
        impression_id TEXT,
        news_id TEXT,
        position INTEGER,
        split TEXT
    );
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def truncate_staging(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE stg_items, stg_sessions, stg_impressions, stg_user_history;")
    conn.commit()


def copy_rows(conn, table: str, columns: list[str], rows: list[list[object]]) -> None:
    if not rows:
        return
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        formatted = []
        for value in row:
            if value is None:
                formatted.append("\\N")
            else:
                formatted.append(value)
        writer.writerow(formatted)
    buffer.seek(0)

    columns_sql = ",".join(columns)
    sql = (
        f"COPY {table} ({columns_sql}) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
    )
    with conn.cursor() as cur:
        cur.copy_expert(sql, buffer)
    conn.commit()


def upsert_items(conn) -> tuple[int, int]:
    sql = """
    WITH upsert AS (
        INSERT INTO items (
            news_id, category, subcategory, title, abstract, url, title_entities, abstract_entities
        )
        SELECT
            news_id,
            category,
            subcategory,
            title,
            abstract,
            url,
            CAST(title_entities AS JSONB),
            CAST(abstract_entities AS JSONB)
        FROM stg_items
        ON CONFLICT (news_id) DO UPDATE SET
            category = EXCLUDED.category,
            subcategory = EXCLUDED.subcategory,
            title = EXCLUDED.title,
            abstract = EXCLUDED.abstract,
            url = EXCLUDED.url,
            title_entities = EXCLUDED.title_entities,
            abstract_entities = EXCLUDED.abstract_entities
        RETURNING (xmax = 0) AS inserted
    )
    SELECT
        COUNT(*) FILTER (WHERE inserted) AS inserted,
        COUNT(*) FILTER (WHERE NOT inserted) AS updated
    FROM upsert;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        inserted, updated = cur.fetchone()
    conn.commit()
    return inserted, updated


def upsert_sessions(conn, split: str) -> tuple[int, int]:
    sql = """
    WITH upsert AS (
        INSERT INTO sessions (impression_id, user_id, time, split)
        SELECT impression_id, user_id, time, split
        FROM stg_sessions
        WHERE split = %s
        ON CONFLICT (split, impression_id) DO UPDATE SET
            user_id = EXCLUDED.user_id,
            time = EXCLUDED.time
        RETURNING (xmax = 0) AS inserted
    )
    SELECT
        COUNT(*) FILTER (WHERE inserted) AS inserted,
        COUNT(*) FILTER (WHERE NOT inserted) AS updated
    FROM upsert;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (split,))
        inserted, updated = cur.fetchone()
    conn.commit()
    return inserted, updated


def upsert_impressions(conn, split: str) -> tuple[int, int]:
    sql = """
    WITH upsert AS (
        INSERT INTO impressions (impression_id, news_id, position, clicked, split)
        SELECT impression_id, news_id, position, clicked, split
        FROM stg_impressions
        WHERE split = %s
        ON CONFLICT (split, impression_id, news_id, position) DO UPDATE SET
            clicked = EXCLUDED.clicked
        RETURNING (xmax = 0) AS inserted
    )
    SELECT
        COUNT(*) FILTER (WHERE inserted) AS inserted,
        COUNT(*) FILTER (WHERE NOT inserted) AS updated
    FROM upsert;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (split,))
        inserted, updated = cur.fetchone()
    conn.commit()
    return inserted, updated


def upsert_user_history(conn, split: str) -> tuple[int, int]:
    sql = """
    WITH upsert AS (
        INSERT INTO user_history (impression_id, news_id, position, split)
        SELECT impression_id, news_id, position, split
        FROM stg_user_history
        WHERE split = %s
        ON CONFLICT (split, impression_id, news_id, position) DO UPDATE SET
            split = EXCLUDED.split
        RETURNING (xmax = 0) AS inserted
    )
    SELECT
        COUNT(*) FILTER (WHERE inserted) AS inserted,
        COUNT(*) FILTER (WHERE NOT inserted) AS updated
    FROM upsert;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (split,))
        inserted, updated = cur.fetchone()
    conn.commit()
    return inserted, updated


def load_items_to_staging(conn, path: str) -> None:
    rows = []
    total = 0
    with open(path, "r", encoding="utf-8") as file:
        for line in tqdm(file, desc="items", unit="lines"):
            parts = line.rstrip("\n").split("\t")
            while len(parts) < 8:
                parts.append("")
            news_id, category, subcategory, title, abstract, url, title_entities, abstract_entities = parts
            title_entities = title_entities or "[]"
            abstract_entities = abstract_entities or "[]"
            rows.append(
                [
                    news_id,
                    category,
                    subcategory,
                    title,
                    abstract,
                    url,
                    title_entities,
                    abstract_entities,
                ]
            )
            if len(rows) >= BATCH_SIZE:
                copy_rows(
                    conn,
                    "stg_items",
                    [
                        "news_id",
                        "category",
                        "subcategory",
                        "title",
                        "abstract",
                        "url",
                        "title_entities",
                        "abstract_entities",
                    ],
                    rows,
                )
                total += len(rows)
                rows.clear()
        if rows:
            copy_rows(
                conn,
                "stg_items",
                [
                    "news_id",
                    "category",
                    "subcategory",
                    "title",
                    "abstract",
                    "url",
                    "title_entities",
                    "abstract_entities",
                ],
                rows,
            )
            total += len(rows)
    return total


def parse_click(entry: str) -> tuple[str, int | None]:
    if "-" in entry:
        news_id, label = entry.rsplit("-", 1)
        if label == "1":
            return news_id, 1
        if label == "0":
            return news_id, 0
        return news_id, None
    return entry, None


def load_behaviors_to_staging(conn, path: str, split: str) -> None:
    sessions_rows = []
    impressions_rows = []
    history_rows = []
    totals = {"sessions": 0, "impressions": 0, "history": 0}

    with open(path, "r", encoding="utf-8") as file:
        for line in tqdm(file, desc=f"behaviors-{split}", unit="lines"):
            parts = line.rstrip("\n").split("\t")
            while len(parts) < 5:
                parts.append("")
            impression_id, user_id, event_time, history, impressions = parts

            sessions_rows.append([impression_id, user_id, event_time, split])

            history_items = history.split(" ") if history else []
            for position, news_id in enumerate([h for h in history_items if h], start=1):
                history_rows.append([impression_id, news_id, position, split])

            impression_items = impressions.split(" ") if impressions else []
            for position, entry in enumerate([i for i in impression_items if i], start=1):
                news_id, label = parse_click(entry)
                clicked = None
                if label == 1:
                    clicked = True
                elif label == 0:
                    clicked = False
                impressions_rows.append([impression_id, news_id, position, clicked, split])

            if len(sessions_rows) >= BATCH_SIZE:
                copy_rows(conn, "stg_sessions", ["impression_id", "user_id", "time", "split"], sessions_rows)
                totals["sessions"] += len(sessions_rows)
                sessions_rows.clear()
            if len(impressions_rows) >= BATCH_SIZE:
                copy_rows(
                    conn,
                    "stg_impressions",
                    ["impression_id", "news_id", "position", "clicked", "split"],
                    impressions_rows,
                )
                totals["impressions"] += len(impressions_rows)
                impressions_rows.clear()
            if len(history_rows) >= BATCH_SIZE:
                copy_rows(
                    conn,
                    "stg_user_history",
                    ["impression_id", "news_id", "position", "split"],
                    history_rows,
                )
                totals["history"] += len(history_rows)
                history_rows.clear()

        if sessions_rows:
            copy_rows(conn, "stg_sessions", ["impression_id", "user_id", "time", "split"], sessions_rows)
            totals["sessions"] += len(sessions_rows)
        if impressions_rows:
            copy_rows(
                conn,
                "stg_impressions",
                ["impression_id", "news_id", "position", "clicked", "split"],
                impressions_rows,
            )
            totals["impressions"] += len(impressions_rows)
        if history_rows:
            copy_rows(
                conn,
                "stg_user_history",
                ["impression_id", "news_id", "position", "split"],
                history_rows,
            )
            totals["history"] += len(history_rows)
    return totals


def ingest_split(conn, split: str, summary: dict) -> None:
    split_dir = os.path.join(EXTRACT_DIR, split)
    news_path = os.path.join(split_dir, "news.tsv")
    behaviors_path = os.path.join(split_dir, "behaviors.tsv")

    if not os.path.isfile(news_path) or not os.path.isfile(behaviors_path):
        raise FileNotFoundError(f"Missing files for split {split} in {split_dir}")

    split_start = time.time()
    truncate_staging(conn)
    print(f"Starting items for split {split}")
    items_staged = load_items_to_staging(conn, news_path)
    print(f"Upserting items for split {split}")
    items_inserted, items_updated = upsert_items(conn)
    summary[split]["items"] = (items_inserted, items_updated)

    truncate_staging(conn)
    print(f"Starting behaviors for split {split}")
    behaviors_totals = load_behaviors_to_staging(conn, behaviors_path, split)

    print(f"Upserting sessions/impressions/user_history for split {split}")
    sessions_inserted, sessions_updated = upsert_sessions(conn, split)
    impressions_inserted, impressions_updated = upsert_impressions(conn, split)
    history_inserted, history_updated = upsert_user_history(conn, split)
    split_elapsed = time.time() - split_start
    print(
        f"Split {split} completed in {split_elapsed:.1f}s "
        f"(items={items_staged}, sessions={behaviors_totals['sessions']}, "
        f"impressions={behaviors_totals['impressions']}, history={behaviors_totals['history']})"
    )

    summary[split]["sessions"] = (sessions_inserted, sessions_updated)
    summary[split]["impressions"] = (impressions_inserted, impressions_updated)
    summary[split]["user_history"] = (history_inserted, history_updated)


def print_summary(summary: dict) -> None:
    print("\nIngestion summary (inserted, updated):")
    for split in SPLITS:
        print(f"\nSplit: {split}")
        for table, counts in summary[split].items():
            inserted, updated = counts
            print(f"  {table}: inserted={inserted} updated={updated}")


def main() -> None:
    load_dotenv()
    conn = get_conn()
    init_tables(conn)

    summary = defaultdict(dict)
    for split in SPLITS:
        ingest_split(conn, split, summary)

    print_summary(summary)
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
