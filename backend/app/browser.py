"""专用浏览器：给需要登录的平台（Boss 直聘等）用。

做法参考 eatmoreduck/boss-zhipin-scraper（MIT）：
1. 用独立的用户目录（data/chrome-profile）启动本机 Chrome，并打开远程调试端口。
   和你平时用的 Chrome 完全隔开，登录态只存在这个目录里。
2. 使用者在这个浏览器里手动登录一次，之后一直复用。
3. 采集时通过 CDP（Chrome DevTools Protocol）只做三件事：打开页面、滚动、旁听页面自己发出的接口响应。
   不注入脚本、不自己发请求（不开 Runtime 域）。平台看到的就是一个真人在用的真浏览器，
   这是目前最不容易触发风控的办法。

为什么不用 Playwright：它连上后会开 Runtime 域等，留下可被检测的痕迹；这里需要的能力很少，
直接用 websocket 发 CDP 命令更干净。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import websockets

from .config import CHROME_PROFILE_DIR

PORT = int(os.getenv("JOB_RADAR_CDP_PORT", "9333"))
BASE = f"http://127.0.0.1:{PORT}"


def find_browser() -> str | None:
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("msedge")


async def is_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            return (await c.get(f"{BASE}/json/version")).status_code == 200
    except httpx.HTTPError:
        return False


async def launch(url: str = "about:blank", minimized: bool = False) -> None:
    """启动专用浏览器；已经开着就只新开一个标签页。

    浏览器通过 cmd 的 start 命令启动，start 结束后浏览器就没有父进程了。
    这样退出或重启求职雷达（会结束后端进程树）时，浏览器不会被一起关掉，正在用的登录也不受影响。
    minimized：检索时自动拉起用最小化，不打扰使用者；手动「打开登录窗口」时正常显示。"""
    if await is_running():
        async with httpx.AsyncClient(timeout=5) as c:
            await c.put(f"{BASE}/json/new?{url}")
        return
    exe = find_browser()
    if not exe:
        raise RuntimeError("没找到 Chrome 或 Edge，请先安装 Chrome")
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={CHROME_PROFILE_DIR}",
            "--no-first-run", "--no-default-browser-check", url]
    if os.name == "nt":
        # 拼成一整条命令：每个参数都加引号（网址里的 & 在 cmd 里有特殊含义）
        cmd = 'cmd /c start "" ' + ("/min " if minimized else "") + " ".join(f'"{a}"' for a in args)
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if await is_running():
            return
        await asyncio.sleep(0.25)
    raise RuntimeError("专用浏览器启动超时")


def open_for_user(url: str) -> None:
    """在专用浏览器里打开一个链接给使用者看（带着登录状态）。

    直接再执行一次 chrome.exe --user-data-dir=同一个目录 网址：Chrome 发现这个目录已经有实例在跑，
    就把网址交给那个实例开一个新标签页，并把窗口带到前台（即使之前是最小化的）。没在跑就正常启动。"""
    exe = find_browser()
    if not exe:
        raise RuntimeError("没找到 Chrome 或 Edge")
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={CHROME_PROFILE_DIR}",
            "--no-first-run", "--no-default-browser-check", url]
    if os.name == "nt":
        cmd = 'cmd /c start "" ' + " ".join(f'"{a}"' for a in args)
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class CDPPage:
    """一个标签页的 CDP 会话。用法：async with CDPPage() as p: await p.navigate(url) ..."""

    def __init__(self):
        self.target: dict | None = None
        self.ws = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue()
        self._reader: asyncio.Task | None = None

    async def __aenter__(self):
        if not await is_running():
            await launch(minimized=True)
        async with httpx.AsyncClient(timeout=5) as c:
            self.target = (await c.put(f"{BASE}/json/new?about:blank")).json()
        self.ws = await websockets.connect(self.target["webSocketDebuggerUrl"], max_size=None)
        self._reader = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc):
        if self._reader:
            self._reader.cancel()
        if self.ws:
            await self.ws.close()
        if self.target:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.get(f"{BASE}/json/close/{self.target['id']}")
            except httpx.HTTPError:
                pass

    async def _read(self):
        async for msg in self.ws:
            data = json.loads(msg)
            if "id" in data and data["id"] in self._pending:
                self._pending.pop(data["id"]).set_result(data)
            elif "method" in data:
                await self.events.put(data)

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict[str, Any]:
        self._id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        res = await asyncio.wait_for(fut, timeout)
        if "error" in res:
            raise RuntimeError(f"CDP {method}: {res['error'].get('message')}")
        return res.get("result", {})

    async def wheel(self, delta_y: int, x: int = 600, y: int = 500):
        """模拟鼠标滚轮（真实输入事件，不执行页面脚本）。"""
        await self.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y})


# 浏览器类信源排队执行：同一时间只开一个标签页，既省资源，也更像一个人在用
BROWSER_LOCK = asyncio.Lock()
# 当前正在检索的信源（由调度器设置）；拿到浏览器的那个信源记在 ACTIVE_SOURCE，界面据此区分「检索中」和「排队中」
import contextvars
CURRENT_SOURCE: contextvars.ContextVar[str] = contextvars.ContextVar("current_source", default="")
ACTIVE_SOURCE = ""
# 两次打开网页之间至少隔这么久（秒，随机取）。多个信源同时到点时会一个一个来，不会连续猛刷
GAP_SECONDS = (20, 45)
_last_release = 0.0


class browser_slot:
    """排队 + 冷却：拿到浏览器使用权后，如果离上一次用完还不到 GAP_SECONDS，先等一会儿。"""

    async def __aenter__(self):
        import random
        import time
        global ACTIVE_SOURCE
        await BROWSER_LOCK.acquire()
        wait = _last_release + random.uniform(*GAP_SECONDS) - time.monotonic()
        ACTIVE_SOURCE = CURRENT_SOURCE.get()
        if wait > 0:
            await asyncio.sleep(wait)
        return self

    async def __aexit__(self, *exc):
        import time
        global _last_release, ACTIVE_SOURCE
        _last_release = time.monotonic()
        ACTIVE_SOURCE = ""
        BROWSER_LOCK.release()


class Visit:
    """打开一个页面，旁听它自己发出的接口响应，或者读取渲染后的 HTML。

    用法：
        async with Visit(url, capture=r"search-pc") as v:
            data = await v.next_json(20)   # 页面自己请求到的 JSON
            html = await v.html()           # 渲染后的页面
    读 HTML 用的是 DOM 域（DOM.getOuterHTML），同样不执行页面脚本。
    """

    def __init__(self, url: str, capture: str | None = None, settle: float = 4.0):
        import re
        self.url = url
        self.capture = re.compile(capture) if capture else None
        self.settle = settle
        self.page: CDPPage | None = None
        self.final_url = url
        self.title = ""
        self._pending: set[str] = set()
        self._bodies: asyncio.Queue = asyncio.Queue()

    async def __aenter__(self):
        self._slot = browser_slot()
        await self._slot.__aenter__()
        try:
            self.page = await CDPPage().__aenter__()
            await self.page.send("Network.enable")
            await self.page.send("Page.enable")
            self._pump = asyncio.create_task(self._watch())
            try:
                await self.page.send("Page.navigate", {"url": self.url}, timeout=45)
            except asyncio.TimeoutError:
                raise RuntimeError("页面打不开（45 秒没有响应），可能是网络问题或网站暂时限制了访问")
            await asyncio.sleep(self.settle)
        except BaseException:
            # 出错也要关掉这个标签页，不然会一直留在专用浏览器里
            try:
                if getattr(self, "_pump", None):
                    self._pump.cancel()
                if self.page:
                    await self.page.__aexit__(None, None, None)
            finally:
                await self._slot.__aexit__()
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            self._pump.cancel()
            await self.page.__aexit__(*exc)
        finally:
            await self._slot.__aexit__()

    async def _watch(self):
        import base64
        while True:
            ev = await self.page.events.get()
            m, p = ev["method"], ev.get("params", {})
            if m == "Page.frameNavigated" and not p.get("frame", {}).get("parentId"):
                self.final_url = p["frame"].get("url", "")
            elif m == "Network.responseReceived" and self.capture and self.capture.search(p.get("response", {}).get("url", "")):
                self._pending.add(p["requestId"])
            elif m == "Network.loadingFinished" and p.get("requestId") in self._pending:
                self._pending.discard(p["requestId"])
                try:
                    body = await self.page.send("Network.getResponseBody", {"requestId": p["requestId"]})
                    text = body.get("body", "")
                    if body.get("base64Encoded"):
                        text = base64.b64decode(text).decode("utf-8", "replace")
                    await self._bodies.put(json.loads(text))
                except Exception:
                    pass

    async def next_json(self, timeout: float = 20) -> Any | None:
        try:
            return await asyncio.wait_for(self._bodies.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def scroll(self, times: int = 3):
        import random
        for _ in range(times):
            await self.page.wheel(random.randint(500, 900))
            await asyncio.sleep(random.uniform(0.8, 1.6))

    async def html(self) -> str:
        doc = await self.page.send("DOM.getDocument", {"depth": 0})
        res = await self.page.send("DOM.getOuterHTML", {"nodeId": doc["root"]["nodeId"]})
        html = res.get("outerHTML", "")
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        self.title = m.group(1).strip() if m else ""
        return html
