"""
migrate_mysql.py
────────────────
One-shot migration: adds the missing columns to the MySQL `emails` table.
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root@localhost/prioritymail")

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

def main():
    print(f"[migrate] Connecting to: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Get existing columns
        result = conn.execute(text("SHOW COLUMNS FROM emails"))
        existing = {row[0] for row in result}
        
        print(f"[migrate] Existing emails columns: {sorted(existing)}")

        added = []
        skipped = []
        for col_name, col_def in NEW_COLUMNS:
            if col_name in existing:
                skipped.append(col_name)
            else:
                sql = text(f"ALTER TABLE emails ADD COLUMN {col_name} {col_def}")
                print(f"[migrate] Running: {sql}")
                conn.execute(sql)
                added.append(col_name)
        
        conn.commit()

    print()
    if added:
        print(f"[migrate] ✅ Added columns: {added}")
    if skipped:
        print(f"[migrate] ⏭  Already existed (skipped): {skipped}")
    print("[migrate] Done.")

if __name__ == "__main__":
    main()
