"""本地服务入口。Electron 启动时拉起这个进程，桌面界面和浏览器里的结果页都通过它取数据。

只监听 127.0.0.1：数据和账号只在本机，局域网里的其他设备访问不到。
"""
from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import browser, db, llm
from .collectors import BROWSER_SOURCES, REGISTRY
from .collectors import boss as boss_mod
from .collectors.webpages import SITES
from .config import DATA_DIR, load_settings, public_settings, save_settings
from .scheduler import scheduler

UI_DIST = Path(os.getenv("JOB_RADAR_UI") or Path(__file__).resolve().parents[2] / "ui" / "dist")
SUMMARY_PATH = DATA_DIR / "summaries.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    scheduler.start()
    db.log("info", "求职雷达已启动")
    yield
    await scheduler.stop()


app = FastAPI(title="job-radar", lifespan=lifespan)
# 开发时界面跑在 Vite（5173 端口），需要跨域；打包后同源，不受影响
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "data_dir": str(DATA_DIR)}


# ---------- 设置 ----------

@app.get("/api/settings")
def get_settings():
    return public_settings(load_settings())


@app.put("/api/settings")
def put_settings(patch: dict = Body(...)):
    llm_patch = patch.get("llm") or {}
    # key 为空字符串表示「不修改」；要清空必须显式传 clear_key
    if "api_key" in llm_patch and not llm_patch["api_key"]:
        llm_patch.pop("api_key")
    if llm_patch.pop("clear_key", False):
        llm_patch["api_key"] = ""
    for f in ("has_key", "key_hint"):
        llm_patch.pop(f, None)
    if "llm" in patch:
        patch["llm"] = llm_patch
    return public_settings(save_settings(patch))


# ---------- 信源与运行 ----------

@app.get("/api/sources")
def sources():
    return list(scheduler.status().values())


@app.post("/api/run")
async def run_now(body: dict = Body(default={})):
    # 必须是 async：检索任务要建在主事件循环上（同步接口跑在线程池里，没有事件循环）
    sid = body.get("source")
    if sid:
        if sid not in REGISTRY:
            raise HTTPException(404, "没有这个信源")
        scheduler.trigger(sid)
        return {"ok": True, "started": [sid]}
    started = scheduler.run_all_now()
    return {"ok": True, "started": started}


@app.post("/api/running")
def set_running(body: dict = Body(...)):
    return public_settings(save_settings({"running": bool(body.get("running"))}))


@app.post("/api/sources/{sid}/resume")
def resume(sid: str):
    save_settings({"sources": {sid: {"paused": "", "paused_reason": ""}}})
    return {"ok": True}


@app.get("/api/overview")
def overview():
    s = load_settings()
    st = scheduler.status()
    activity = {
        "running": [x["id"] for x in st.values() if x["state"] == "running"],
        "queued": [x["id"] for x in st.values() if x["state"] == "queued"],
        # 还没被 AI 整理的岗位数（填了 key 且开着自动整理时才会处理）
        "pending_enrich": db.conn().execute("SELECT COUNT(*) FROM jobs WHERE enriched=0").fetchone()[0]
        if s["llm"].get("api_key") and s["llm"].get("enrich") else 0,
    }
    return {"stats": db.job_stats(), "sources": list(st.values()), "running": s["running"], "activity": activity,
            "has_key": bool(s["llm"].get("api_key")), "onboarded": s["onboarded"],
            "has_keywords": bool(s["criteria"]["keywords"])}


@app.get("/api/runs")
def runs(limit: int = 100):
    return db.recent_runs(limit)


@app.get("/api/logs")
def logs(limit: int = 300, after: int = 0):
    return db.recent_logs(limit, after)


# ---------- 岗位 ----------

def _split(v: str | None) -> list[str] | None:
    return [x for x in v.split(",") if x] if v else None


@app.get("/api/jobs")
def jobs(days: int | None = None, date: str | None = None, source: str | None = None, region: str | None = None,
         remote: bool = False, type: str | None = None, status: str | None = None, q: str = "",
         min_score: int | None = None, sort: str = "new", limit: int = Query(500, le=2000)):
    rows = db.query_jobs(days=days, date=date, sources=_split(source), regions=_split(region), remote_only=remote,
                         job_types=_split(type), statuses=_split(status), q=q, min_score=min_score, sort=sort, limit=limit)
    return {"jobs": rows, "count": len(rows)}


@app.get("/api/jobs/serial/{serial}")
def job_by_serial(serial: int):
    """AI 回答里写的「#588」→ 对应的岗位（界面上点编号直接打开）。"""
    row = db.conn().execute("SELECT id FROM jobs WHERE serial=?", (serial,)).fetchone()
    if not row:
        raise HTTPException(404, "没有这个编号的岗位")
    return db.get_job(row["id"])


@app.patch("/api/jobs/{job_id}")
def patch_job(job_id: str, body: dict = Body(...)):
    if body.get("status") not in ("new", "seen", "starred", "applied", "dismissed"):
        raise HTTPException(400, "状态不对")
    db.update_job(job_id, {"status": body["status"]})
    return db.get_job(job_id)


@app.get("/api/stats")
def stats():
    return db.job_stats()


# ---------- 专用浏览器 / 登录 ----------

LOGIN_URLS = {"boss": boss_mod.LOGIN_URL, "bing": "https://cn.bing.com/", **{k: s.home for k, s in SITES.items()}}


@app.get("/api/browser/platforms")
def browser_platforms():
    """「账号与登录」页：所有要用专用浏览器的平台，以及它们最近一次的状态。"""
    st = scheduler.status()
    out = []
    for sid in REGISTRY:
        if sid not in BROWSER_SOURCES:
            continue
        x = st[sid]
        site = SITES.get(sid)
        out.append({"id": sid, "name": x["name"], "group": x["group"], "enabled": x["config"].get("enabled"),
                    "state": x["state"], "paused_reason": x["config"].get("paused_reason") or "",
                    "last_error": (x["last_run"] or {}).get("error") if x["last_run"] and not x["last_run"]["ok"] else "",
                    "needs_login": bool(site.needs_login) if site else sid == "boss",
                    "verify_once": bool(site.verify_once) if site else False, "home": LOGIN_URLS.get(sid, "")})
    return out


@app.get("/api/browser/status")
async def browser_status():
    return {"running": await browser.is_running(), "browser": browser.find_browser()}


@app.post("/api/browser/open")
async def browser_open(body: dict = Body(default={})):
    url = LOGIN_URLS.get(body.get("platform") or "", body.get("url") or "about:blank")
    try:
        await browser.launch(url)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/open")
def open_link(body: dict = Body(...)):
    """用专用浏览器打开岗位链接（有登录状态，Boss、小红书等平台的详情才看得全）。"""
    url = str(body.get("url") or "")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "不是有效的链接")
    try:
        browser.open_for_user(url)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/login/{platform}/check")
async def login_check(platform: str):
    if platform != "boss":
        raise HTTPException(404, "暂不支持")
    try:
        state, why = await boss_mod.probe()
    except Exception as e:
        return {"state": "error", "message": f"检测失败：{e}"}
    if state == "ok":
        save_settings({"sources": {"boss": {"paused": "", "paused_reason": "", "login_checked_at": db.now()}}})
    return {"state": state, "message": why or "已登录，可以正常检索"}


# ---------- AI ----------

@app.post("/api/llm/test")
async def llm_test(body: dict = Body(default={})):
    s = load_settings()
    cfg = {**s["llm"], **{k: v for k, v in body.items() if v}}
    try:
        msg = await llm.chat(cfg, [{"role": "user", "content": "回复「连接正常」四个字"}], timeout=30, kind="test")
    except llm.LLMError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"连不上：{e}"}
    return {"ok": True, "message": (msg.get("content") or "").strip()[:50]}


@app.get("/api/usage")
def usage(days: int = 30):
    s = load_settings()
    return {**db.usage_summary(days), "price": s["llm"].get("price"), "peak_now": llm.is_peak()}


@app.post("/api/assistant/upload")
async def assistant_upload(file: UploadFile = File(...)):
    """上传简历等附件：读成文字，去掉手机号 / 邮箱 / 证件号，再交给前端放进对话。"""
    from . import agent_tools
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件太大（超过 10MB）")
    try:
        text = agent_tools.extract_text(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"读不出文字：{e}")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 20:
        raise HTTPException(400, "没读到文字（可能是扫描件 / 图片版 PDF）")
    masked, n = agent_tools.mask_contacts(text)
    return {"name": file.filename, "text": masked[:12000], "chars": len(masked), "masked": n}


@app.post("/api/assistant/proposals/{pid}/apply")
def apply_proposal(pid: str):
    from . import agent_tools
    try:
        return agent_tools.apply_proposal(pid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/assistant/proposals/{pid}/discard")
def discard_proposal(pid: str):
    from . import agent_tools
    agent_tools.discard(pid)
    return {"ok": True}


@app.post("/api/assistant")
async def assistant(body: dict = Body(...)):
    s = load_settings()
    try:
        return await llm.assistant(s["llm"], s["criteria"], body.get("messages") or [])
    except llm.LLMError as e:
        raise HTTPException(400, str(e))


def _summaries() -> dict:
    try:
        return json.loads(SUMMARY_PATH.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@app.get("/api/summary")
def get_summary(date: str):
    return _summaries().get(date) or {}


@app.post("/api/summary")
async def make_summary(body: dict = Body(...)):
    day = body.get("date") or datetime.now().date().isoformat()
    s = load_settings()
    # 只总结 AI 没判「不合适」的；当天一条都没有就退回到最近 7 天，不直接报错
    rows = db.query_jobs(date=day, sort="score", limit=300)
    good, scope = [r for r in rows if r.get("verdict") != "no"], f"{day} 这一天"
    hidden = len(rows) - len(good)
    if not good:
        rows = db.query_jobs(days=7, sort="score", limit=300)
        good, scope = [r for r in rows if r.get("verdict") != "no"], "最近 7 天"
        hidden = len(rows) - len(good)
    if not good:
        raise HTTPException(400, f"最近 7 天还没有值得看的岗位（AI 判为不合适的有 {hidden} 条）。可以先点「立即检索」，或者放宽搜索条件。")
    try:
        text = await llm.summarize(s["llm"], s["criteria"], good, scope, hidden)
    except llm.LLMError as e:
        raise HTTPException(400, str(e))
    allsum = _summaries()
    allsum[day] = {"text": text, "count": len(good), "hidden": hidden, "scope": scope, "at": db.now()}
    SUMMARY_PATH.write_text(json.dumps(allsum, ensure_ascii=False, indent=1), "utf-8")
    return allsum[day]


# ---------- 导出：生成一个单文件 H5，可以发到手机或发给别人看 ----------

@app.get("/api/export")
def export(days: int = 7):
    # 用单独构建的单文件版结果页（ui/vite.standalone.config.ts），JS / CSS 都已内联，可以离线打开
    tpl = UI_DIST / "standalone" / "report.html"
    if not tpl.exists():
        raise HTTPException(404, "导出模板还没构建，请先在 ui 目录运行 npm run build")
    rows = db.query_jobs(days=days, limit=2000)
    # 把数据直接嵌进页面，结果页检测到 window.__SNAPSHOT__ 就不再请求接口
    payload = json.dumps({"jobs": rows, "at": db.now(), "days": days}, ensure_ascii=False).replace("</", r"<\/")
    html = tpl.read_text("utf-8").replace("<head>", f"<head><script>window.__SNAPSHOT__={payload}</script>", 1)
    name = f"job-radar-{datetime.now():%Y%m%d-%H%M}.html"
    out = DATA_DIR / "exports"
    out.mkdir(exist_ok=True)
    (out / name).write_text(html, "utf-8")
    return {"path": str(out / name), "name": name, "count": len(rows)}


# ---------- 静态页面 ----------

if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/report", response_class=HTMLResponse)
    def report_page():
        return FileResponse(UI_DIST / "report.html")

    @app.get("/", response_class=HTMLResponse)
    def index_page():
        return FileResponse(UI_DIST / "index.html")

    @app.get("/{name}")
    def root_file(name: str):
        # dist 根目录下的小文件（icon.svg 等）；只认文件名，不允许带路径
        p = UI_DIST / name
        if "/" in name or "\\" in name or not p.is_file():
            raise HTTPException(404)
        return FileResponse(p)


def run():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("JOB_RADAR_PORT", "17860")), log_level="warning")


if __name__ == "__main__":
    run()
