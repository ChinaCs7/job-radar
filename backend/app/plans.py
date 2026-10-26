"""Search plans own criteria and evaluations; job facts are shared locally."""
from __future__ import annotations
import copy
import json
import uuid
from . import db
from .plan_context import current_plan


def migrate():
    from .config import load_global_settings
    c = db.conn()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS plans (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, person TEXT NOT NULL,
      criteria TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '{}',
      running INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'active',
      revision INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS plan_jobs (
      plan_id TEXT NOT NULL, job_id TEXT NOT NULL, first_seen TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'new', filtered INTEGER DEFAULT 0,
      score INTEGER, score_reason TEXT DEFAULT '', verdict TEXT DEFAULT '',
      verdict_reason TEXT DEFAULT '', ai_summary TEXT DEFAULT '',
      evaluated INTEGER DEFAULT 0, revision INTEGER DEFAULT 1,
      attempts INTEGER DEFAULT 0, retry_at TEXT DEFAULT '',
      PRIMARY KEY(plan_id, job_id));
    CREATE INDEX IF NOT EXISTS idx_plan_pending ON plan_jobs(plan_id,evaluated);
    CREATE TABLE IF NOT EXISTS search_cursors (
      plan_id TEXT, source TEXT, signature TEXT, cursor INTEGER DEFAULT 0,
      PRIMARY KEY(plan_id,source,signature));
    CREATE TABLE IF NOT EXISTS proposals (
      id TEXT PRIMARY KEY, plan_id TEXT, revision INTEGER, payload TEXT,
      state TEXT DEFAULT 'pending', created_at TEXT);
    CREATE TABLE IF NOT EXISTS collector_cache (
      key TEXT PRIMARY KEY, at TEXT, jobs TEXT);
    CREATE TABLE IF NOT EXISTS fact_cache (
      key TEXT PRIMARY KEY, facts TEXT NOT NULL);
    ''')
    if 'evaluation_enabled' not in {r[1] for r in c.execute('PRAGMA table_info(plans)')}:
        c.execute('ALTER TABLE plans ADD COLUMN evaluation_enabled INTEGER NOT NULL DEFAULT 1')
    for table in ('runs', 'logs', 'llm_usage'):
        columns = {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
        if 'plan_id' not in columns:
            c.execute(f"ALTER TABLE {table} ADD COLUMN plan_id TEXT DEFAULT 'legacy'")
    columns = {r[1] for r in c.execute('PRAGMA table_info(runs)')}
    for col, definition in [('kept','INTEGER DEFAULT 0'),('updated','INTEGER DEFAULT 0'),
                            ('unchanged','INTEGER DEFAULT 0'),('detail','TEXT DEFAULT \'\'')]:
        if col not in columns:
            c.execute(f'ALTER TABLE runs ADD COLUMN {col} {definition}')
    if not c.execute('SELECT 1 FROM plans LIMIT 1').fetchone():
        s = load_global_settings()
        s['sources'].setdefault('boss',{})['max_pages']=max(2,int(s['sources'].get('boss',{}).get('max_pages',1)))
        stamp = db.now()
        c.execute('INSERT INTO plans(id,name,person,criteria,sources,running,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                  ('legacy','原有求职方案','我',json.dumps(s['criteria'],ensure_ascii=False),
                   json.dumps(s['sources'],ensure_ascii=False),0,stamp,stamp))
        c.execute("UPDATE plans SET evaluation_enabled=0 WHERE id='legacy'")
        # Preserve manual decisions; old AI judgments belong to unknown historical criteria.
        c.execute("""INSERT OR IGNORE INTO plan_jobs(plan_id,job_id,first_seen,status)
          SELECT 'legacy',id,first_seen,CASE WHEN status='filtered' THEN 'new' ELSE status END FROM jobs""")
    c.commit()


def get(plan_id: str | None = None, include_deleted=False) -> dict:
    pid = plan_id or current_plan.get() or 'legacy'
    r = db.conn().execute('SELECT * FROM plans WHERE id=?',(pid,)).fetchone()
    if not r or (r['state']=='deleted' and not include_deleted):
        raise ValueError('方案不存在或已移入回收区，请重新选择方案')
    out = dict(r)
    out['criteria'] = json.loads(out['criteria'])
    out['sources'] = json.loads(out['sources'])
    out['running'] = bool(out['running'])
    return out


def listing(include_deleted=False) -> list[dict]:
    rows = db.conn().execute("SELECT id FROM plans WHERE state!='deleted' OR ? ORDER BY created_at,id",(int(include_deleted),))
    out=[]
    for row in rows.fetchall():
        p=get(row['id'],True)
        counts=dict(db.conn().execute("""SELECT COUNT(*) candidates,
          COALESCE(SUM(filtered=0 AND verdict!='no'),0) visible,
          COALESCE(SUM(evaluated=0),0) pending,
          COALESCE(SUM(filtered=0 AND verdict='recommend'),0) recommended
          FROM plan_jobs WHERE plan_id=?""",(p['id'],)).fetchone())
        out.append({**p,**counts})
    return out


def clean_criteria(value: dict, base: dict | None = None) -> dict:
    from .config import DEFAULT_SETTINGS, _merge
    from .agent_tools import mask_contacts
    if not isinstance(value,dict): raise ValueError('搜索条件必须是对象')
    out = _merge(base or DEFAULT_SETTINGS['criteria'],value)
    for k in ('keywords','cities','exclude','job_types'):
        if not isinstance(out[k],list) or any(not isinstance(x,str) for x in out[k]):
            raise ValueError(f'{k} 必须是文字列表')
        out[k]=list(dict.fromkeys(x.strip()[:80] for x in out[k] if x.strip()))[:30]
    if not out['job_types'] or any(x not in ('fulltime','parttime','intern','contract') for x in out['job_types']):
        raise ValueError('至少选择一种有效的岗位类型')
    if not isinstance(out['regions'],dict) or not any(out['regions'].get(k) for k in ('domestic','overseas','remote')):
        raise ValueError('至少选择一个地区范围')
    out['regions']={k:bool(out['regions'].get(k)) for k in ('domestic','overseas','remote')}
    out['salary_min_k']=max(0,min(1000,float(out.get('salary_min_k') or 0)))
    out['max_age_days']=max(0,min(365,int(out.get('max_age_days',30))))
    out['profile']=mask_contacts(str(out.get('profile') or '')[:4000])[0]
    return {k:out[k] for k in DEFAULT_SETTINGS['criteria']}


def create(data: dict) -> dict:
    name=str(data.get('name') or '').strip()[:100]
    if not name: raise ValueError('请填写方案名称')
    person=str(data.get('person') or '我').strip()[:60] or '我'
    criteria=clean_criteria(data.get('criteria') or {})
    from .collectors import REGISTRY
    sources=data.get('sources') or {}
    if not isinstance(sources,dict): raise ValueError('信源配置必须是对象')
    sources={k:v for k,v in sources.items() if k in REGISTRY and isinstance(v,dict)}
    # New plans start with selected core sources, never inherit another person's preferences.
    if not sources:
        sources={sid:{'enabled':sid in ('boss','liepin','51job','zhilian','company','v2ex','eleduck')}
                 for sid in REGISTRY}
    pid=uuid.uuid4().hex
    stamp=db.now()
    with db._write_lock:
        db.conn().execute('INSERT INTO plans(id,name,person,criteria,sources,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
            (pid,name,person,json.dumps(criteria,ensure_ascii=False),json.dumps(sources,ensure_ascii=False),stamp,stamp))
        db.conn().commit()
    return get(pid)


def update(pid: str, patch: dict) -> dict:
    from .config import _merge
    with db._write_lock:
        p=get(pid,True)
        expected=patch.get('revision')
        if expected is not None and int(expected)!=p['revision']:
            raise ValueError('方案已被修改，请刷新后重试')
        criteria=clean_criteria(patch.get('criteria') or {},p['criteria'])
        changed=criteria!=p['criteria']
        name=str(patch.get('name',p['name'])).strip()[:100]
        person=str(patch.get('person',p['person'])).strip()[:60]
        if not name or not person: raise ValueError('方案名称和求职者不能为空')
        state=patch.get('state',p['state'])
        if state not in ('active','archived','deleted'): raise ValueError('无效的方案状态')
        running=bool(patch.get('running',p['running'])) and state=='active'
        if running and not criteria['keywords']: raise ValueError('先填写关键词，再开启自动检索')
        sources=_merge(p['sources'],patch.get('sources') or {})
        revision=p['revision']+1
        c=db.conn()
        c.execute('UPDATE plans SET name=?,person=?,criteria=?,sources=?,running=?,state=?,revision=?,updated_at=? WHERE id=?',
            (name,person,json.dumps(criteria,ensure_ascii=False),json.dumps(sources,ensure_ascii=False),int(running),state,revision,db.now(),pid))
        if changed:
            c.execute('UPDATE plans SET evaluation_enabled=1 WHERE id=?',(pid,))
            c.execute("""UPDATE plan_jobs SET evaluated=0,filtered=0,score=NULL,score_reason='',verdict='',
              verdict_reason='',ai_summary='',attempts=0,retry_at='',revision=? WHERE plan_id=?""",(revision,pid))
            c.execute('DELETE FROM search_cursors WHERE plan_id=?',(pid,))
        else:
            c.execute('UPDATE plan_jobs SET revision=? WHERE plan_id=?',(revision,pid))
        c.commit()
    return get(pid,True)


def copy_plan(pid: str) -> dict:
    p=get(pid)
    return create({'name':p['name']+' · 副本','person':p['person'],'criteria':p['criteria'],'sources':p['sources']})


def rotate(source: str, items: list, budget: int) -> list:
    """Fair round-robin across searches; cursor is persisted per plan and query set."""
    import hashlib
    if not items: return []
    pid=current_plan.get() or 'legacy'
    sig=hashlib.sha256(json.dumps(items,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    c=db.conn()
    r=c.execute('SELECT cursor FROM search_cursors WHERE plan_id=? AND source=? AND signature=?',(pid,source,sig)).fetchone()
    start=(r[0] if r else 0)%len(items)
    n=min(max(1,budget),len(items))
    selected=[items[(start+i)%len(items)] for i in range(n)]
    c.execute('INSERT OR REPLACE INTO search_cursors VALUES(?,?,?,?)',(pid,source,sig,(start+n)%len(items)))
    c.commit()
    db.log('info',f'本轮覆盖 {n}/{len(items)} 个搜索组合，从第 {start+1} 个开始；其余组合后续轮转',source)
    return selected
