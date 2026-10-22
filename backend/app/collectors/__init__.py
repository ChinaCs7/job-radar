from .base import Collector, CollectorError, SourceInfo
from .boss import Boss
from .companies import DEFAULT_COMPANIES, Companies
from .overseas import Himalayas, JobSpy, Remotive, WeWorkRemotely
from .simple import Eleduck, HackerNews, RemoteOK, V2ex
from .webpages import SITES, BingSearch, WebPage
from .websearch import WebSearch

# 顺序就是界面上的显示顺序：招聘平台 → 公司官网 → 社区 → 媒体平台 → 全网搜索 → 海外与远程
_order = [
    Boss(), WebPage(SITES["liepin"]), WebPage(SITES["51job"]), WebPage(SITES["zhilian"]), WebPage(SITES["lagou"]),
    WebPage(SITES["58"]), WebPage(SITES["nowcoder"]),
    Companies(), WebPage(SITES["xhsjobs"]),
    V2ex(), Eleduck(),
    WebPage(SITES["xiaohongshu"]), WebPage(SITES["zhihu"]), WebPage(SITES["weibo"]), WebPage(SITES["maimai"]),
    WebPage(SITES["jike"]),
    BingSearch(), WebSearch(),
    JobSpy(), RemoteOK(), Remotive(), Himalayas(), WeWorkRemotely(), HackerNews(),
]
REGISTRY: dict[str, Collector] = {c.info.id: c for c in _order}

# 需要用专用浏览器的信源（界面上标「浏览器」，并在「账号与登录」里列出）
BROWSER_SOURCES = {"boss", *SITES.keys(), "bing"}

__all__ = ["REGISTRY", "BROWSER_SOURCES", "DEFAULT_COMPANIES", "Collector", "CollectorError", "SourceInfo"]
