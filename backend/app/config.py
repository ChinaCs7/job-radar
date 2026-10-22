"""配置与数据目录。

所有用户数据（设置、数据库、专用浏览器的登录态）都放在一个数据目录里：
- 开发时：项目下的 data/（被 git 忽略）
- 打包后：%APPDATA%/job-radar（Electron 通过环境变量 JOB_RADAR_DATA 传进来）
这样朋友装了以后，账号和 key 只存在他自己的电脑上。
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.getenv("JOB_RADAR_DATA") or Path(__file__).resolve().parents[2] / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "jobs.db"
CHROME_PROFILE_DIR = DATA_DIR / "chrome-profile"

# 每个信源的默认开关和间隔（分钟）。
# 需要登录的平台间隔拉长、夜里暂停：宁可慢，不要封号。
_MEDIA_SITES = ["xiaohongshu.com", "maimai.cn", "zhihu.com", "okjike.com", "nowcoder.com", "weibo.com"]
_login = {"interval_min": 180, "night_pause": True}   # 要登录的平台：间隔长、夜里停
DEFAULT_SOURCES = {
    # 招聘平台（浏览器）
    "boss":     {"enabled": True,  "interval_min": 180, "night_pause": True,  "max_pages": 1, "max_combos": 3},
    "liepin":   {"enabled": True,  "interval_min": 120, "night_pause": True},
    "51job":    {"enabled": True,  "interval_min": 120, "night_pause": True},
    "zhilian":  {"enabled": False, "interval_min": 180, "night_pause": True},   # 要登录
    "lagou":    {"enabled": True,  "interval_min": 180, "night_pause": True},
    "58":       {"enabled": False, "interval_min": 240, "night_pause": True},   # 站内搜索不认技术关键词，结果多为普工岗
    "nowcoder": {"enabled": True,  "interval_min": 180, "night_pause": True},
    # 公司官网
    "company":  {"enabled": True,  "interval_min": 120, "night_pause": False},
    "xhsjobs":  {"enabled": True,  "interval_min": 240, "night_pause": True},
    # 社区
    "v2ex":     {"enabled": True,  "interval_min": 30,  "night_pause": False},
    "eleduck":  {"enabled": True,  "interval_min": 30,  "night_pause": False},
    # 媒体平台：要登录，默认关闭
    "xiaohongshu": {"enabled": False, **_login},
    "zhihu":    {"enabled": False, **_login},
    "weibo":    {"enabled": False, **_login},
    "maimai":   {"enabled": False, **_login},
    "jike":     {"enabled": False, **_login},
    # 全网搜索：必应免费，DeepSeek 付费
    "bing":     {"enabled": True,  "interval_min": 240, "night_pause": True, "sites": _MEDIA_SITES, "max_queries": 10},
    "websearch": {"enabled": False, "interval_min": 240, "night_pause": False, "sites": _MEDIA_SITES},
    # 海外与远程
    "jobspy":   {"enabled": True,  "interval_min": 180, "night_pause": False, "sites": ["linkedin", "indeed", "google"]},
    "remoteok": {"enabled": True,  "interval_min": 120, "night_pause": False},
    "remotive": {"enabled": True,  "interval_min": 180, "night_pause": False},
    "himalayas": {"enabled": True, "interval_min": 180, "night_pause": False},
    "wwr":      {"enabled": True,  "interval_min": 180, "night_pause": False},
    "hn":       {"enabled": True,  "interval_min": 360, "night_pause": False},
}

DEFAULT_SETTINGS = {
    "onboarded": False,
    "running": False,          # 自动检索总开关
    "theme": "system",         # light / dark / system
    "criteria": {
        "keywords": [],         # 例：["AI Agent", "大模型应用"]
        "cities": [],           # 例：["厦门", "上海"]；空 = 不限
        "salary_min_k": 0,      # 月薪下限（K），0 = 不限
        "job_types": ["fulltime", "parttime", "intern", "contract"],
        "exclude": [],          # 标题或公司里出现就丢掉，例：["外包", "销售"]
        "regions": {"domestic": True, "overseas": True, "remote": True},
        "profile": "",          # 一段自我介绍，给 AI 打匹配分用
        "max_age_days": 30,     # 只要最近 N 天发布的；0 = 不限。平台没给发布时间的，由 AI 从正文判断
    },
    "sources": DEFAULT_SOURCES,
    "llm": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "enrich": True,         # 新岗位用大模型整理字段、打分
        # 价格（元 / 百万 tokens，高峰时段；空闲时段按 off_peak_ratio 折算）。来源：DeepSeek 官网「模型 & 价格」，2026-10
        "price": {"input_hit": 0.04, "input_miss": 2.0, "output": 8.0, "search_per_1k": 5.0, "off_peak_ratio": 0.5},
    },
    "night": {"start": 1, "end": 7},  # 夜间暂停的时段（本地时间，小时）
}

_lock = threading.Lock()


def _merge(base: dict, override: dict) -> dict:
    """把用户保存的设置合并到默认值上，新版本加的字段自动补齐。"""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    with _lock:
        if SETTINGS_PATH.exists():
            try:
                saved = json.loads(SETTINGS_PATH.read_text("utf-8"))
            except json.JSONDecodeError:
                saved = {}
        else:
            saved = {}
        return _merge(DEFAULT_SETTINGS, saved)


def save_settings(patch: dict) -> dict:
    current = load_settings()
    merged = _merge(current, patch)
    with _lock:
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(SETTINGS_PATH)
    return merged


def public_settings(s: dict) -> dict:
    """返回给界面的设置：key 只告诉界面「填没填」，不回传原文。"""
    out = copy.deepcopy(s)
    key = out["llm"].get("api_key") or ""
    out["llm"]["api_key"] = ""
    out["llm"]["has_key"] = bool(key)
    out["llm"]["key_hint"] = f"…{key[-4:]}" if len(key) >= 8 else ""
    return out
