import os
import time

import psycopg
from psycopg.rows import dict_row

from rules import judge

DSN = os.environ["DATABASE_URL"]

INITIAL_TOLERANCE_MM = 0.15


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
            """CREATE TABLE IF NOT EXISTS jobs (
                id serial PRIMARY KEY,
                sheet text NOT NULL,
                cyan_mm double precision NOT NULL,
                magenta_mm double precision NOT NULL,
                status text NOT NULL,
                verdict text NOT NULL DEFAULT '',
                reason text NOT NULL DEFAULT '',
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                tolerance_mm double precision
            )"""
        )
        # 旧卷升级：领取瞬间记下的允差快照
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tolerance_mm double precision")
        # 允差改档记录，只增不改；最新一档即现行允差
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tolerance_revisions (
                id serial PRIMARY KEY,
                tolerance_mm double precision NOT NULL,
                changed_by text NOT NULL,
                reason text NOT NULL DEFAULT '',
                changed_at timestamptz NOT NULL
            )"""
        )
        # 初始档：仅在改档表为空时插入。咨询锁串行化 api/worker 并发启动，避免重复初始档
        conn.execute("SELECT pg_advisory_xact_lock(910273)")
        conn.execute(
            """INSERT INTO tolerance_revisions (tolerance_mm, changed_by, reason, changed_at)
               SELECT %s, 'system', '初始允差档', now()
               WHERE NOT EXISTS (SELECT 1 FROM tolerance_revisions)""",
            (INITIAL_TOLERANCE_MM,),
        )
        conn.commit()


def claim_once(conn):
    # 同一个行锁事务内：领走 pending 任务、读此刻现行允差、把允差快照写到任务上。
    # 正在领取（running）的任务不受后续改档影响；新档只作用于尚未领取的新队。
    row = conn.execute(
        """WITH picked AS (
             SELECT id FROM jobs
             WHERE status = 'pending'
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
           ),
           current_tol AS (
             SELECT tolerance_mm FROM tolerance_revisions ORDER BY id DESC LIMIT 1
           )
           UPDATE jobs
           SET status = 'running',
               tolerance_mm = (SELECT tolerance_mm FROM current_tol)
           FROM picked
           WHERE jobs.id = picked.id
           RETURNING jobs.id, jobs.cyan_mm, jobs.magenta_mm, jobs.tolerance_mm"""
    ).fetchone()
    return row


def main():
    ensure()
    while True:
        with connect() as conn:
            row = claim_once(conn)
            if row is None:
                conn.commit()
            else:
                verdict, reason = judge(
                    row["cyan_mm"], row["magenta_mm"], row["tolerance_mm"]
                )
                conn.execute(
                    "UPDATE jobs SET status = 'done', verdict = %s, reason = %s WHERE id = %s",
                    (verdict, reason, row["id"]),
                )
                conn.commit()
        if row is None:
            time.sleep(0.4)


if __name__ == "__main__":
    main()
