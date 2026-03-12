"""
migrate_db.py
─────────────
One-shot migration: adds the columns that the ORM model defines but
that were not present in the original database schema.

Safe to run multiple times — it checks before each ALTER TABLE.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "prioritymail.db")

NEW_COLUMNS = [
    # (column_name, sql_type_and_default)
    ("priority",            "VARCHAR(20) DEFAULT 'low'"),
    ("needs_attention_now", "BOOLEAN DEFAULT 0"),
    ("waiting",             "BOOLEAN DEFAULT 0"),
    ("form_detected",       "BOOLEAN DEFAULT 0"),
    ("form_description",    "VARCHAR(1024)"),
    ("body_html",           "TEXT"),
    ("meeting_duration",    "VARCHAR(10)"),
]


def get_existing_columns(cursor, table: str) -> set:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def main():
    print(f"[migrate] Connecting to: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing = get_existing_columns(cursor, "emails")
    print(f"[migrate] Existing emails columns: {sorted(existing)}")

    added = []
    skipped = []
    for col_name, col_def in NEW_COLUMNS:
        if col_name in existing:
            skipped.append(col_name)
        else:
            sql = f"ALTER TABLE emails ADD COLUMN {col_name} {col_def}"
            print(f"[migrate] Running: {sql}")
            cursor.execute(sql)
            added.append(col_name)

    conn.commit()
    conn.close()

    print()
    if added:
        print(f"[migrate] ✅ Added columns: {added}")
    if skipped:
        print(f"[migrate] ⏭  Already existed (skipped): {skipped}")
    print("[migrate] Done.")


if __name__ == "__main__":
    main()
