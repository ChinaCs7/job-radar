"""调度器：每个信源按自己的间隔轮流检索，互不影响。

- 间隔加 ±15% 随机抖动，避免每次都在整点、固定节奏地访问平台。
- night_pause 的信源在夜间时段不跑（需要登录的平台默认开启）。
- 出现 blocked（被风控）或 login（登录失效）时，暂停该信源并写进设置，等使用者处理后点「恢复」。
  绝不自动重试被风控的平台：重试只会让账号风险更高。
- 另有一个后台循环，每 20 秒把新岗位交给大模型整理一批。
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta

from . import db, pipeline
from .collectors import BROWSER_SOURCES, DEFAULT_COMPANIES, REGISTRY
from .config import load_settings, save_settings


class Scheduler:
    def __init__(self):
        self.next_run: dict[str, datetime] = {}
        self.running: set[str] = set()
        self._tasks: list[asyncio.Task] = []

    def start(self):
        self._tasks = [asyncio.create_task(self._loop()), asyncio.create_task(self._enrich_loop())]

    async def stop(self):
        for t in self._tasks:
            t.cancel()

    @staticmethod
    def in_night(s: dict, t: datetime) -> bool:
        a, b = s["night"]["start"], s["night"]["end"]
        return a <= t.hour < b if a < b else (t.hour >= a or t.hour < b)

    @staticmethod
    def region_wanted(s: dict, sid: str) -> bool:
        """海外和远程都关掉时，纯海外的信源就没必要跑了。"""
        r = s["criteria"]["regions"]
        return not (REGISTRY[sid].info.region == "overseas" and not r.get("overseas") and not r.get("remote"))

    @staticmethod
    def daily_cap(sid: str, cfg: dict) -> int:
        """浏览器类信源每天最多检索几次（防封）。可在设置里按信源改 max_runs_per_day。"""
        default = 6 if sid == "boss" else 10 if sid in BROWSER_SOURCES else 48
        return int(cfg.get("max_runs_per_day", default))

    def over_daily_cap(self, sid: str, cfg: dict) -> bool:
        return db.runs_today(sid) >= self.daily_cap(sid, cfg)

    @staticmethod
    def morning(s: dict) -> int:
        return int(s["night"]["end"])

    def _schedule_next(self, sid: str, cfg: dict):
        minutes = max(5, int(cfg.get("interval_min", 60)))
        self.next_run[sid] = datetime.now() + timedelta(minutes=minutes * random.uniform(0.85, 1.15))

    async def _loop(self):
        while True:
            try:
                s = load_settings()
                if s.get("running"):
                    now = datetime.now()
                    for sid, cfg in s["sources"].items():
                        if sid not in REGISTRY or not cfg.get("enabled") or cfg.get("paused") or sid in self.running:
                            continue
                        if not self.region_wanted(s, sid):
                            continue
                        if cfg.get("night_pause") and self.in_night(s, now):
                            continue
                        if sid not in self.next_run:
                            # 刚启动 / 刚打开自动检索：各信源错开开始，浏览器类的散得更开
                            spread = 20 * 60 if sid in BROWSER_SOURCES else 5 * 60
                            self.next_run[sid] = now + timedelta(seconds=random.uniform(30, spread))
                            continue
                        if self.next_run[sid] <= now:
                            if self.over_daily_cap(sid, cfg):
                                self.next_run[sid] = (now + timedelta(days=1)).replace(hour=self.morning(s), minute=random.randint(0, 40))
                                db.log("info", f"{REGISTRY[sid].info.name} 今天已检索 {db.runs_today(sid)} 次，到上限了，明天再继续", sid)
                                continue
                            self.trigger(sid)
            except Exception as e:  # 调度循环本身不能死
                db.log("error", f"调度器异常：{e}")
            await asyncio.sleep(5)

    def trigger(self, sid: str):
        if sid in self.running:
            return
        self.running.add(sid)
        asyncio.create_task(self._run(sid))

    async def _run(self, sid: str):
        from . import browser
        browser.CURRENT_SOURCE.set(sid)
        try:
            res = await pipeline.run_source(sid)
            if res.get("kind") in ("blocked", "login"):
                save_settings({"sources": {sid: {"paused": res["kind"], "paused_reason": res["error"]}}})
        finally:
            self.running.discard(sid)
            self._schedule_next(sid, load_settings()["sources"].get(sid, {}))

    def run_all_now(self):
        """「立即检索」：接口类信源马上跑；浏览器类排队（每次之间有冷却），到了每日上限的跳过。"""
        s = load_settings()
        started: list[str] = []
        for sid, cfg in s["sources"].items():
            if sid in REGISTRY and cfg.get("enabled") and not cfg.get("paused") and self.region_wanted(s, sid):
                if self.over_daily_cap(sid, cfg) or sid in self.running:
                    continue
                self.trigger(sid)
                started.append(sid)
        return started

    async def _enrich_loop(self):
        while True:
            try:
                n = await pipeline.enrich_pending()
            except Exception as e:
                db.log("error", f"AI 整理异常：{e}", "llm")
                n = 0
            await asyncio.sleep(3 if n else 20)

    def status(self) -> dict[str, dict]:
        from . import browser
        s = load_settings()
        last = db.last_runs()
        stats = db.job_stats()["by_source"]
        out = {}
        for sid, col in REGISTRY.items():
            cfg = s["sources"].get(sid, {})
            nr = self.next_run.get(sid)
            if not cfg.get("enabled"):
                state = "disabled"
            elif sid in self.running:
                # 浏览器类：没拿到浏览器的都在排队
                state = "queued" if sid in BROWSER_SOURCES and browser.ACTIVE_SOURCE != sid else "running"
            elif cfg.get("paused"):
                state = "paused"
            elif last.get(sid) and not last[sid]["ok"]:
                state = "error"
            else:
                state = "ok" if last.get(sid) else "idle"
            out[sid] = {
                "id": sid, "name": col.info.name, "group": col.info.group, "region": col.info.region,
                "browser": sid in BROWSER_SOURCES,
                "needs_login": col.info.needs_login, "needs_key": col.info.needs_key, "note": col.info.note,
                "config": {**cfg, "companies": cfg.get("companies") or DEFAULT_COMPANIES} if sid == "company" else cfg,
                "state": state, "last_run": last.get(sid), "total": stats.get(sid, 0),
                "next_run": nr.isoformat(timespec="seconds") if nr and s.get("running") and state not in ("disabled", "paused") else None,
                "night_now": bool(cfg.get("night_pause") and self.in_night(s, datetime.now())),
            }
        return out


scheduler = Scheduler()
