"""Plan-scoped scheduling with global per-platform budgets and cancellable tasks."""
from __future__ import annotations
import asyncio
import random
from datetime import datetime, timedelta
from . import db, plans, pipeline
from .collectors import BROWSER_SOURCES, DEFAULT_COMPANIES, REGISTRY
from .config import load_settings, save_global_settings
from .plan_context import current_plan, scope
from .execution import PROGRESS

class Scheduler:
    def __init__(self):
        self.next_run = {}
        self.tasks = {}
        self._tasks = []

    def start(self):
        self._tasks = [asyncio.create_task(self._loop()), asyncio.create_task(self._enrich_loop())]

    async def stop(self):
        tasks = [*self._tasks, *self.tasks.values()]
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def in_night(s, t):
        a,b=s['night']['start'],s['night']['end']
        return a<=t.hour<b if a<b else t.hour>=a or t.hour<b

    @staticmethod
    def region_wanted(s,sid):
        r=s['criteria']['regions']
        return not(REGISTRY[sid].info.region=='overseas' and not r.get('overseas') and not r.get('remote'))

    @staticmethod
    def daily_cap(sid,cfg):
        return int(cfg.get('max_runs_per_day',6 if sid=='boss' else 10 if sid in BROWSER_SOURCES else 48))

    def over_daily_cap(self,sid,cfg):
        return db.runs_today(sid)>=self.daily_cap(sid,cfg)

    def trigger(self,sid):
        pid=current_plan.get() or 'legacy'
        s=load_settings(); p=plans.get(pid); cfg=s['sources'].get(sid,{})
        key=(pid,sid)
        if key in self.tasks: return False
        if p['state']!='active': raise ValueError('方案已归档或删除，请先恢复')
        if not p['criteria']['keywords']: raise ValueError('请先填写方案关键词')
        if not cfg.get('enabled'): raise ValueError('当前方案没有启用这个信源')
        if cfg.get('paused'): raise ValueError('该平台需要登录或验证，请先处理后恢复')
        if not self.region_wanted(s,sid): return False
        reserved=sum(1 for k in self.tasks if k[1]==sid)
        if db.runs_today(sid)+reserved>=self.daily_cap(sid,cfg): return False
        task=asyncio.create_task(self._run(pid,sid))
        self.tasks[key]=task
        # Cancellation before the coroutine's first instruction cannot run its finally block.
        def release(done):
            if self.tasks.get(key) is done: self.tasks.pop(key,None)
        task.add_done_callback(release)
        return True

    async def _run(self,pid,sid):
        from . import browser
        with scope(pid):
            browser.CURRENT_SOURCE.set(sid)
            try:
                res=await pipeline.run_source(sid)
                if res.get('kind') in ('blocked','login'):
                    save_global_settings({'sources':{sid:{'paused':res['kind'],'paused_reason':res['error']}}})
            finally:
                self.tasks.pop((pid,sid),None)
                try: cfg=load_settings()['sources'].get(sid,{})
                except ValueError: cfg={}
                minutes=max(5,int(cfg.get('interval_min',60)))
                self.next_run[(pid,sid)]=datetime.now()+timedelta(minutes=minutes*random.uniform(.85,1.15))

    def run_all_now(self):
        s=load_settings(); started=[]
        for sid,cfg in s['sources'].items():
            if sid in REGISTRY and cfg.get('enabled') and not cfg.get('paused'):
                if self.trigger(sid): started.append(sid)
        return started

    def cancel(self,pid,source=None):
        count=0
        for (p,sid),task in list(self.tasks.items()):
            if p==pid and (not source or source==sid): task.cancel(); count+=1
        return count

    async def _loop(self):
        while True:
            try:
                for p in plans.listing():
                    if p['state']!='active' or not p['running']: continue
                    with scope(p['id']):
                        s=load_settings(); now=datetime.now()
                        for sid,cfg in s['sources'].items():
                            if sid not in REGISTRY or not cfg.get('enabled') or cfg.get('paused'): continue
                            if cfg.get('night_pause') and self.in_night(s,now): continue
                            key=(p['id'],sid)
                            if key not in self.next_run:
                                self.next_run[key]=now+timedelta(seconds=random.uniform(30,1200 if sid in BROWSER_SOURCES else 300))
                            if self.next_run[key]<=now: self.trigger(sid)
            except Exception as e: db.log('error',f'调度器异常：{e}')
            await asyncio.sleep(5)

    async def _enrich_loop(self):
        while True:
            n=0
            for p in plans.listing():
                if p['state']!='active': continue
                try:
                    with scope(p['id']): n+=await pipeline.enrich_pending()
                except Exception as e: db.log('error',f'AI 评估异常：{e}','llm')
            await asyncio.sleep(3 if n else 20)

    def status(self):
        from . import browser
        pid=current_plan.get() or 'legacy'
        s=load_settings(); last=db.last_runs(); stats=db.job_stats()['by_source']; out={}
        for sid,col in REGISTRY.items():
            cfg=s['sources'].get(sid,{}); key=(pid,sid); nr=self.next_run.get(key)
            if not cfg.get('enabled'): state='disabled'
            elif key in self.tasks:
                state='queued' if sid in BROWSER_SOURCES and browser.ACTIVE_TASK!=key else 'running'
            elif cfg.get('paused'): state='paused'
            elif last.get(sid) and not last[sid]['ok']: state='error'
            else: state='ok' if last.get(sid) else 'idle'
            out[sid]={'id':sid,'name':col.info.name,'group':col.info.group,'region':col.info.region,
                'browser':sid in BROWSER_SOURCES,'needs_login':col.info.needs_login,'needs_key':col.info.needs_key,'note':col.info.note,
                'config':{**cfg,'companies':cfg.get('companies') or DEFAULT_COMPANIES} if sid=='company' else cfg,
                'state':state,'last_run':last.get(sid),'total':stats.get(sid,0),
                'next_run':nr.isoformat(timespec='seconds') if nr and s['running'] and state not in ('disabled','paused') else None,
                'night_now':bool(cfg.get('night_pause') and self.in_night(s,datetime.now())),
                'progress':PROGRESS.get(key), 'daily_used':db.runs_today(sid),'daily_cap':self.daily_cap(sid,cfg)}
        return out

scheduler=Scheduler()
