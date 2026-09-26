import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, field_validator
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54394/printreg")
SECRET = os.environ.get("JWT_SECRET", "print-register-dev-secret")
DEFAULT_TOLERANCE_MM = 0.15
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "printer": {"role": "writer", "password_hash": pwd.hash("print123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS tolerance_settings (
    id integer PRIMARY KEY DEFAULT 1,
    tolerance_mm double precision NOT NULL,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT tolerance_singleton CHECK (id = 1)
);
CREATE TABLE IF NOT EXISTS tolerance_history (
    id serial PRIMARY KEY,
    tolerance_mm double precision NOT NULL,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
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
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tolerance_mm double precision;
"""


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    sheet: str
    cyan_mm: float
    magenta_mm: float


class ToleranceIn(BaseModel):
    tolerance_mm: float

    @field_validator("tolerance_mm")
    @classmethod
    def check_range(cls, value: float) -> float:
        if value != value or value <= 0 or value > 10:
            raise ValueError("允差需为 0 到 10 毫米之间的正数")
        return value


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅印刷员可操作")
    return user


app = FastAPI(title="印刷套准复核台")


@app.on_event("startup")
def startup():
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute(SCHEMA)
        # 现行允差档：没有就落默认 0.15，并写一条初始改档记录
        conn.execute(
            """INSERT INTO tolerance_settings (id, tolerance_mm, updated_by, updated_at)
               VALUES (1, %s, 'system', %s)
               ON CONFLICT (id) DO NOTHING""",
            (DEFAULT_TOLERANCE_MM, now),
        )
        seeded = conn.execute("SELECT COUNT(*) AS n FROM tolerance_history").fetchone()["n"]
        if seeded == 0:
            conn.execute(
                """INSERT INTO tolerance_history (tolerance_mm, changed_by, changed_at)
                   VALUES (%s, 'system', %s)""",
                (DEFAULT_TOLERANCE_MM, now),
            )
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            conn.execute(
                """INSERT INTO jobs (sheet, cyan_mm, magenta_mm, status, verdict, reason, created_by, created_at)
                   VALUES
                   ('封面-01', 0.05, -0.04, 'pending', '', '', 'printer', %s),
                   ('内页-09', 0.40, 0.02, 'pending', '', '', 'printer', %s)""",
                (now, now),
            )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "print-register-review"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/jobs")
def list_jobs(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT id, sheet, cyan_mm, magenta_mm, status, verdict, reason,
                      tolerance_mm, created_by
               FROM jobs ORDER BY id DESC"""
        ).fetchall()


@app.post("/api/jobs", status_code=202)
def enqueue(body: JobIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO jobs (sheet, cyan_mm, magenta_mm, status, created_by, created_at)
               VALUES (%s, %s, %s, 'pending', %s, %s)
               RETURNING id, sheet, status, verdict""",
            (body.sheet.strip(), body.cyan_mm, body.magenta_mm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


@app.get("/api/tolerance")
def get_tolerance(_user: dict = Depends(current_user)):
    """现行允差档。只读账号同样可见。"""
    with connect() as conn:
        return conn.execute(
            "SELECT tolerance_mm, updated_by, updated_at FROM tolerance_settings WHERE id = 1"
        ).fetchone()


@app.get("/api/tolerance/history")
def tolerance_history(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT id, tolerance_mm, changed_by, changed_at
               FROM tolerance_history ORDER BY id DESC LIMIT 50"""
        ).fetchall()


@app.put("/api/tolerance")
def update_tolerance(body: ToleranceIn, user: dict = Depends(require_writer)):
    """改档只落新档与历史；正在领取中的任务不受影响，领取瞬间快照的旧档继续用。"""
    now = datetime.now(timezone.utc)
    with connect() as conn:
        current = conn.execute(
            "SELECT tolerance_mm FROM tolerance_settings WHERE id = 1 FOR UPDATE"
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=500, detail="允差档未初始化")
        if current["tolerance_mm"] != body.tolerance_mm:
            conn.execute(
                "UPDATE tolerance_settings SET tolerance_mm = %s, updated_by = %s, updated_at = %s WHERE id = 1",
                (body.tolerance_mm, user["username"], now),
            )
            conn.execute(
                """INSERT INTO tolerance_history (tolerance_mm, changed_by, changed_at)
                   VALUES (%s, %s, %s)""",
                (body.tolerance_mm, user["username"], now),
            )
        row = conn.execute(
            "SELECT tolerance_mm, updated_by, updated_at FROM tolerance_settings WHERE id = 1"
        ).fetchone()
        conn.commit()
    return row
