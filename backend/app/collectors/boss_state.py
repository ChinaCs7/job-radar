"""Durable Boss coverage and detail retry state. No account tokens are stored here."""
import hashlib
import json
from datetime import datetime, timedelta
from .. import db
from ..models import Job
from ..plan_context import current_plan


def init():
    db.conn().executescript('''
    CREATE TABLE IF NOT EXISTS boss_pages (
      plan_id TEXT, signature TEXT, next_page INTEGER DEFAULT 1, rounds INTEGER DEFAULT 0,
      PRIMARY KEY(plan_id,signature));
    CREATE TABLE IF NOT EXISTS boss_details (
      job_id TEXT PRIMARY KEY, payload TEXT, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
      retry_at TEXT DEFAULT '', checked_at TEXT DEFAULT '', error TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS boss_detail_plans (plan_id TEXT, job_id TEXT, PRIMARY KEY(plan_id,job_id));
    CREATE TABLE IF NOT EXISTS boss_receipts (
      id INTEGER PRIMARY KEY, plan_id TEXT, at TEXT, payload TEXT);
    ''')


def page_start(keyword,city):
    init()
    pid=current_plan.get() or 'legacy'
    sig=hashlib.sha256(json.dumps([keyword,city]).encode()).hexdigest()
    db.conn().execute('INSERT OR IGNORE INTO boss_pages(plan_id,signature) VALUES(?,?)',(pid,sig))
    row=db.conn().execute('SELECT * FROM boss_pages WHERE plan_id=? AND signature=?',(pid,sig)).fetchone()
    # Every third successful round revisits the head; the deep scan position is retained.
    head=row['rounds']>0 and row['rounds']%3==0
    db.conn().commit()
    return sig,1 if head else row['next_page'],head


def page_saved(signature,page,has_more,head=False):
    pid=current_plan.get() or 'legacy'
    row=db.conn().execute('SELECT next_page FROM boss_pages WHERE plan_id=? AND signature=?',(pid,signature)).fetchone()
    next_page=(max(row[0],page+1) if head else page+1) if has_more is not False else 1
    db.conn().execute('UPDATE boss_pages SET next_page=? WHERE plan_id=? AND signature=?',(next_page,pid,signature))
    db.conn().commit()


def round_done(signature):
    db.conn().execute('UPDATE boss_pages SET rounds=rounds+1 WHERE plan_id=? AND signature=?',(current_plan.get() or 'legacy',signature))
    db.conn().commit()


def enqueue(jobs):
    from dataclasses import asdict
    init()
    for job in jobs:
        db.conn().execute('''INSERT INTO boss_details(job_id,payload) VALUES(?,?)
          ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload''',
          (job.id,json.dumps(asdict(job),ensure_ascii=False)))
        db.conn().execute('INSERT OR IGNORE INTO boss_detail_plans VALUES(?,?)',(current_plan.get() or 'legacy',job.id))
    db.conn().commit()


def pending(limit, criteria=None):
    from ..pipeline import passes
    rows=db.conn().execute('''SELECT d.* FROM boss_details d JOIN boss_detail_plans p ON p.job_id=d.job_id
      WHERE p.plan_id=? AND d.retry_at<=? AND d.state!='exhausted'
      ORDER BY CASE WHEN d.state='pending' THEN 0 ELSE 1 END,d.checked_at,d.job_id''',
      (current_plan.get() or 'legacy',db.now())).fetchall()
    selected=[]
    for r in rows:
        if len(selected)>=limit: break
        job=Job(**json.loads(r['payload']))
        if criteria is None or passes(job.__dict__,criteria)[0]:
            selected.append((job,r['attempts']))
    return selected


def detail_done(job_id,success,error='',blocked=False):
    row=db.conn().execute('SELECT attempts FROM boss_details WHERE job_id=?',(job_id,)).fetchone()
    attempts=0 if success else row[0]+(0 if blocked else 1)
    state='complete' if success else 'exhausted' if attempts>=3 else 'retry'
    delay=timedelta(days=7) if success else timedelta(hours=1 if blocked else min(24,2**attempts))
    db.conn().execute('UPDATE boss_details SET state=?,attempts=?,retry_at=?,checked_at=?,error=? WHERE job_id=?',
      (state,attempts,(datetime.now()+delay).isoformat(),db.now(),error[:300],job_id))
    db.conn().commit()


def receipt(payload):
    init()
    db.conn().execute('INSERT INTO boss_receipts(plan_id,at,payload) VALUES(?,?,?)',
      (current_plan.get() or 'legacy',db.now(),json.dumps(payload,ensure_ascii=False)))
    db.conn().commit()
