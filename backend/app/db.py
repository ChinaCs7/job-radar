"""SQLite 存储。

两张主表：
- jobs：一行 = 某个信源上的一个岗位。同一岗位在多个平台出现时是多行，用 cluster_key 串起来，
  结果页显示成一条，并列出「另见」的其他平台链接。
- runs：每次检索的记录（哪个信源、几点、找到几条、新增几条、出了什么错），给运行日志和信源状态用。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

from .config import DB_PATH
from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  serial INTEGER,                -- 全局流水号，界面上显示成「#1284」
  title TEXT NOT NULL,
  company TEXT, city TEXT, region TEXT, remote INTEGER DEFAULT 0,
  salary TEXT, salary_min_k REAL, job_type TEXT,
  experience TEXT, education TEXT, tags TEXT, description TEXT,
  url TEXT NOT NULL, platform TEXT, published_at TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  cluster_key TEXT,
  score INTEGER, score_reason TEXT, ai_summary TEXT,
  enriched INTEGER DEFAULT 0, needs_enrich INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new',     -- new / seen / starred / applied / dismissed
  raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_cluster ON jobs(cluster_key);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER,
  found INTEGER DEFAULT 0,
  added INTEGER DEFAULT 0,
  error TEXT,
  error_kind TEXT                -- login / blocked / network / other
);
CREATE INDEX IF NOT EXISTS idx_runs_source ON runs(source, id);

-- 大模型和搜索接口的每一次调用：用来统计 token 和花费
CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,            -- enrich（整理岗位）/ summary（总结）/ assistant（AI 助手）/ search（DeepSeek 搜索）/ test
  model TEXT,
  prompt_tokens INTEGER DEFAULT 0,
  cache_hit_tokens INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  requests INTEGER DEFAULT 1,
  peak INTEGER DEFAULT 0,        -- 是否高峰时段（价格翻倍）
  cost REAL DEFAULT 0            -- 估算花费（元）
);
CREATE INDEX IF NOT EXISTS idx_usage_at ON llm_usage(at);

CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, level TEXT NOT NULL, source TEXT, message TEXT NOT NULL
);
"""

_local = threading.local()
_write_lock = threading.Lock()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


CLUSTER_VERSION = 2   # 去重规则变了就加 1，启动时会按新规则重算所有岗位的 cluster_key


def init() -> None:
    with _write_lock:
        c = conn()
        c.executescript(SCHEMA)
        # 新版本加的列（旧数据库没有）：AI 翻译的中文标题、AI 结论（推荐 / 可以看看 / 不合适）和理由
        have = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        for col in ("title_zh", "verdict", "verdict_reason"):
            if col not in have:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT DEFAULT ''")
        c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        row = c.execute("SELECT v FROM meta WHERE k='cluster_version'").fetchone()
        if not row or int(row[0]) < CLUSTER_VERSION:
            from .models import cluster_key
            for r in c.execute("SELECT id, company, title FROM jobs").fetchall():
                c.execute("UPDATE jobs SET cluster_key=? WHERE id=?", (cluster_key(r["company"], r["title"]), r["id"]))
            c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('cluster_version', ?)", (str(CLUSTER_VERSION),))
        # 0.1 版的「腾讯招聘」信源已并入「公司官网」，旧记录改成同一个平台名，免得被当成两个平台
        c.execute("UPDATE jobs SET platform='腾讯官网' WHERE source='tencent' AND platform='腾讯招聘'")
        c.commit()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- jobs ----------

def upsert_jobs(jobs: list[Job]) -> list[str]:
    """写入岗位，返回新增岗位的 id。已存在的只更新 last_seen（说明还挂着）。"""
    added: list[str] = []
    t = now()
    with _write_lock:
        c = conn()
        for j in jobs:
            row = c.execute("SELECT id FROM jobs WHERE id=?", (j.id,)).fetchone()
            if row:
                c.execute("UPDATE jobs SET last_seen=? WHERE id=?", (t, j.id))
                continue
            serial = (c.execute("SELECT COALESCE(MAX(serial),0)+1 FROM jobs").fetchone()[0])
            c.execute(
                """INSERT INTO jobs (id, source, external_id, serial, title, company, city, region, remote,
                   salary, salary_min_k, job_type, experience, education, tags, description, url, platform,
                   published_at, first_seen, last_seen, cluster_key, needs_enrich, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (j.id, j.source, j.external_id, serial, j.title, j.company, j.city, j.region, int(j.remote),
                 j.salary, j.salary_min_k, j.job_type, j.experience, j.education,
                 json.dumps(j.tags, ensure_ascii=False), j.description[:4000], j.url, j.platform,
                 j.published_at, t, t, j.cluster_key, int(j.needs_enrich),
                 json.dumps(j.raw, ensure_ascii=False, default=str)[:20000]),
            )
            added.append(j.id)
        c.commit()
    return added


def update_job(job_id: str, fields: dict[str, Any]) -> None:
    allowed = {"title", "company", "city", "region", "remote", "salary", "salary_min_k", "job_type",
               "tags", "description", "score", "score_reason", "ai_summary", "enriched", "status",
               "cluster_key", "experience", "education", "title_zh", "verdict", "verdict_reason", "published_at"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    if "tags" in sets and not isinstance(sets["tags"], str):
        sets["tags"] = json.dumps(sets["tags"], ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in sets)
    with _write_lock:
        conn().execute(f"UPDATE jobs SET {cols} WHERE id=?", (*sets.values(), job_id))
        conn().commit()


def delete_job(job_id: str) -> None:
    with _write_lock:
        conn().execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn().commit()


def get_job(job_id: str) -> dict | None:
    r = conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(r) if r else None


def jobs_to_enrich(limit: int = 20) -> list[dict]:
    rows = conn().execute(
        "SELECT * FROM jobs WHERE enriched=0 ORDER BY first_seen DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["remote"] = bool(d.get("remote"))
    d.pop("raw", None)
    return d


def query_jobs(*, days: int | None = None, date: str | None = None, sources: list[str] | None = None,
               regions: list[str] | None = None, remote_only: bool = False, job_types: list[str] | None = None,
               statuses: list[str] | None = None, q: str = "", min_score: int | None = None,
               sort: str = "new", limit: int = 500, group: bool = True) -> list[dict]:
    """结果页和 AI 助手共用的查询。group=True 时同一 cluster 只返回一条主记录，其余放进 also。"""
    where, args = [], []
    if date:
        where.append("substr(first_seen,1,10)=?"); args.append(date)
    elif days:
        where.append("first_seen>=?"); args.append((datetime.now() - timedelta(days=days)).isoformat())
    if sources:
        where.append(f"source IN ({','.join('?' * len(sources))})"); args += sources
    if regions:
        where.append(f"region IN ({','.join('?' * len(regions))})"); args += regions
    if remote_only:
        where.append("remote=1")
    if job_types:
        where.append(f"(job_type IN ({','.join('?' * len(job_types))}) OR job_type='' OR job_type IS NULL)")
        args += job_types
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})"); args += statuses
    else:
        # filtered = 大模型整理后发现不是岗位或不符合条件；dismissed = 使用者标了不合适。默认都不显示
        where.append("status NOT IN ('dismissed','filtered')")
    if q:
        where.append("(title LIKE ? OR company LIKE ? OR description LIKE ? OR city LIKE ?)")
        args += [f"%{q}%"] * 4
    if min_score is not None:
        where.append("COALESCE(score,0)>=?"); args.append(min_score)
    order = {"new": "first_seen DESC", "score": "COALESCE(score,-1) DESC, first_seen DESC",
             "salary": "COALESCE(salary_min_k,-1) DESC"}.get(sort, "first_seen DESC")
    sql = f"SELECT * FROM jobs {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY {order} LIMIT ?"
    rows = [_row(r) for r in conn().execute(sql, (*args, limit * 3 if group else limit)).fetchall()]
    if not group:
        return rows
    out, seen = [], {}
    for r in rows:
        k = r.get("cluster_key")
        if k and k in seen:
            seen[k]["also"].append({"source": r["source"], "platform": r["platform"], "url": r["url"], "id": r["id"]})
            continue
        r["also"] = []
        if k:
            seen[k] = r
        out.append(r)
    # 补齐：同 cluster 但不在本次筛选范围里的旧记录，也作为「另见」
    keys = [r["cluster_key"] for r in out if r.get("cluster_key")]
    if keys:
        ids = {r["id"] for r in rows}
        for chunk in (keys[i:i + 400] for i in range(0, len(keys), 400)):
            for o in conn().execute(
                    f"SELECT id, source, platform, url, cluster_key FROM jobs WHERE cluster_key IN ({','.join('?' * len(chunk))})",
                    chunk).fetchall():
                if o["id"] not in ids and o["cluster_key"] in seen:
                    seen[o["cluster_key"]]["also"].append(dict(o))
    return out[:limit]


def job_stats() -> dict:
    c = conn()
    today = datetime.now().date().isoformat()
    visible = "status NOT IN ('dismissed','filtered')"
    total = c.execute(f"SELECT COUNT(*) FROM jobs WHERE {visible} AND COALESCE(verdict,'')!='no'").fetchone()[0]
    # 口径和岗位页的默认视图一致：AI 判为「不合适」的单独计数，不算进「新增」
    ok = f"{visible} AND COALESCE(verdict,'')!='no'"
    today_n = c.execute(f"SELECT COUNT(*) FROM jobs WHERE {ok} AND substr(first_seen,1,10)=?", (today,)).fetchone()[0]
    today_no = c.execute(f"SELECT COUNT(*) FROM jobs WHERE {visible} AND verdict='no' AND substr(first_seen,1,10)=?", (today,)).fetchone()[0]
    high = c.execute(f"SELECT COUNT(*) FROM jobs WHERE {visible} AND verdict='recommend' AND substr(first_seen,1,10)=?", (today,)).fetchone()[0]
    rec_total = c.execute(f"SELECT COUNT(*) FROM jobs WHERE {visible} AND verdict='recommend'").fetchone()[0]
    by_day = [dict(r) for r in c.execute(
        f"SELECT substr(first_seen,1,10) AS day, COUNT(*) AS n FROM jobs WHERE {visible} GROUP BY day ORDER BY day DESC LIMIT 30")]
    by_source = {r["source"]: r["n"] for r in c.execute(f"SELECT source, COUNT(*) n FROM jobs WHERE {visible} GROUP BY source")}
    return {"total": total, "today": today_n, "today_no": today_no, "today_high": high, "recommend_total": rec_total,
            "by_day": by_day, "by_source": by_source}


# ---------- runs & logs ----------

def run_start(source: str) -> int:
    with _write_lock:
        cur = conn().execute("INSERT INTO runs (source, started_at) VALUES (?,?)", (source, now()))
        conn().commit()
        return cur.lastrowid


def run_finish(run_id: int, *, ok: bool, found: int = 0, added: int = 0, error: str = "", error_kind: str = "") -> None:
    with _write_lock:
        conn().execute("UPDATE runs SET finished_at=?, ok=?, found=?, added=?, error=?, error_kind=? WHERE id=?",
                       (now(), int(ok), found, added, error[:1000], error_kind, run_id))
        conn().commit()


def last_runs() -> dict[str, dict]:
    rows = conn().execute(
        "SELECT r.* FROM runs r JOIN (SELECT source, MAX(id) mid FROM runs GROUP BY source) m ON r.id=m.mid").fetchall()
    return {r["source"]: dict(r) for r in rows}


def runs_today(source: str) -> int:
    return conn().execute("SELECT COUNT(*) FROM runs WHERE source=? AND substr(started_at,1,10)=?",
                          (source, datetime.now().date().isoformat())).fetchone()[0]


def recent_runs(limit: int = 100) -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


def add_usage(kind: str, model: str, prompt: int, hit: int, completion: int, requests: int, peak: bool, cost: float) -> None:
    with _write_lock:
        conn().execute(
            "INSERT INTO llm_usage (at, kind, model, prompt_tokens, cache_hit_tokens, completion_tokens, requests, peak, cost) "
            "VALUES (?,?,?,?,?,?,?,?,?)", (now(), kind, model, prompt, hit, completion, requests, int(peak), cost))
        conn().commit()


def usage_summary(days: int = 30) -> dict:
    c = conn()
    since = (datetime.now() - timedelta(days=days)).date().isoformat()
    cols = ("COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS prompt, COALESCE(SUM(cache_hit_tokens),0) AS hit, "
            "COALESCE(SUM(completion_tokens),0) AS completion, COALESCE(SUM(requests),0) AS requests, COALESCE(SUM(cost),0) AS cost")
    today = datetime.now().date().isoformat()
    month = datetime.now().strftime("%Y-%m")
    return {
        "today": dict(c.execute(f"SELECT {cols} FROM llm_usage WHERE substr(at,1,10)=?", (today,)).fetchone()),
        "month": dict(c.execute(f"SELECT {cols} FROM llm_usage WHERE substr(at,1,7)=?", (month,)).fetchone()),
        "total": dict(c.execute(f"SELECT {cols} FROM llm_usage").fetchone()),
        "by_day": [dict(r) for r in c.execute(
            f"SELECT substr(at,1,10) AS day, {cols} FROM llm_usage WHERE substr(at,1,10)>=? GROUP BY day ORDER BY day DESC", (since,))],
        "by_kind": [dict(r) for r in c.execute(
            f"SELECT kind, {cols} FROM llm_usage WHERE substr(at,1,10)>=? GROUP BY kind ORDER BY cost DESC", (since,))],
        "recent": [dict(r) for r in c.execute("SELECT * FROM llm_usage ORDER BY id DESC LIMIT 200")],
    }


def log(level: str, message: str, source: str = "") -> None:
    with _write_lock:
        conn().execute("INSERT INTO logs (at, level, source, message) VALUES (?,?,?,?)", (now(), level, source, message[:2000]))
        conn().execute("DELETE FROM logs WHERE id < (SELECT MAX(id) - 5000 FROM logs)")
        conn().commit()


def recent_logs(limit: int = 300, after_id: int = 0) -> list[dict]:
    return [dict(r) for r in conn().execute(
        "SELECT * FROM logs WHERE id>? ORDER BY id DESC LIMIT ?", (after_id, limit))]
