import os
import time
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from rules import judge

DSN = os.environ["DATABASE_URL"]
DEFAULT_TOLERANCE_MM = 0.15


def connect():
    last = None
    for _ in range(40):
        try:
            return psycopg.connect(DSN, row_factory=dict_row)
        except psycopg.OperationalError as exc:
            last = exc
            time.sleep(1)
    raise last


def ensure():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tolerance_settings (
                id integer PRIMARY KEY DEFAULT 1,
                tolerance_mm double precision NOT NULL,
                updated_by text NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT tolerance_singleton CHECK (id = 1)
            )"""
        )
        conn.execute(
            """INSERT INTO tolerance_settings (id, tolerance_mm, updated_by, updated_at)
               VALUES (1, %s, 'system', %s)
               ON CONFLICT (id) DO NOTHING""",
            (DEFAULT_TOLERANCE_MM, datetime.now(timezone.utc)),
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id serial PRIMARY KEY,
                sheet text NOT NULL,
                cyan_mm double precision NOT NULL,
                magenta_mm double precision NOT NULL,
                status text NOT NULL,
                verdict text NOT NULL DEFAULT '',
                reason text NOT NULL DEFAULT '',
                tolerance_mm double precision,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tolerance_mm double precision")
        conn.commit()


def claim_once(conn):
    # 同一条 UPDATE 内读此刻的允差并快照到任务上：
    # 改档只影响尚未领取的新任务，已领取的继续用记下的旧档。
    row = conn.execute(
        """WITH picked AS (
             SELECT id FROM jobs
             WHERE status = 'pending'
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
           )
           UPDATE jobs
              SET status = 'running',
                  tolerance_mm = (SELECT tolerance_mm FROM tolerance_settings WHERE id = 1)
            FROM picked
           WHERE jobs.id = picked.id
           RETURNING jobs.id, jobs.cyan_mm, jobs.magenta_mm, jobs.tolerance_mm"""
    ).fetchone()
    return row


def main():
    ensure()
    while True:
        idle = False
        with connect() as conn:
            row = claim_once(conn)
            if row is None:
                idle = True
                conn.commit()
            elif row["tolerance_mm"] is None:
                # 允差档缺失（理论上 ensure 已兜底）：退回队列稍后再领
                conn.execute("UPDATE jobs SET status = 'pending' WHERE id = %s", (row["id"],))
                idle = True
                conn.commit()
            else:
                verdict, reason = judge(row["cyan_mm"], row["magenta_mm"], row["tolerance_mm"])
                conn.execute(
                    "UPDATE jobs SET status = 'done', verdict = %s, reason = %s WHERE id = %s",
                    (verdict, reason, row["id"]),
                )
                conn.commit()
        if idle:
            time.sleep(0.4)


if __name__ == "__main__":
    main()
