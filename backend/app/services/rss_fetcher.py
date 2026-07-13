"""新闻抓取服务 (rss_fetcher.py)
=================================
职责：从多个中英文金融/科技信源并发抓取新闻，返回去重后的原始新闻列表。

当前活跃信源（24 个）：
  财经类：富途新闻（通过 JSON API，快讯流）
         MarketWatch / Seeking Alpha / CNBC / Investing.com（RSS/Atom XML）
         Reuters / Yahoo Finance（通过 Google News RSS 按站点过滤，无需 RSSHub）
         SEC EDGAR（Atom，一手 8-K filing 流，UA 需带联系邮箱）
         Finnhub（通过 JSON API，需 API Key）
  科技类：TechCrunch / OpenAI Blog / Google AI Blog / Anthropic /
         Hugging Face / MIT Tech Review / MarkTechPost / The Verge AI /
         Last Week in AI / The Gradient / NVIDIA Blog / Simon Willison（RSS/Atom XML）
         arXiv(cs.AI, cs.CL)（RSS/Atom XML，论文流）
         Hacker News（通过 Algolia API）

  注：Benzinga 因 Cloudflare 拦截（403）且无可用端点已移除；
      MarkTechPost 同样可能被 Cloudflare 挑战，保留其 RSSHub 备用路由；
      Reuters/Yahoo 依赖公共 RSSHub 实例，可通过环境变量 RSSHUB_INSTANCES 覆盖。

处理流程：
  1. 使用 httpx 并发请求所有信源
  2. 每个信源有独立的解析器（adapter），解析各自的 JSON/XML 结构
  3. 对每条新闻 URL 做 SHA-256 哈希，查 Redis Set 判断是否已处理过
  4. 正则预过滤：丢弃含「推广/广告/赞助」等关键词的标题
  5. 返回 RawNewsItem 列表，交给下游去重和 DeepSeek 评分

容错机制：
  - 每个信源独立 try/except，单源失败不影响整个 pipeline
  - 支持 fallback URL + 指数退避重试（429/503 时触发）
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import feedparser
import httpx
import redis.asyncio as aioredis
from bs4 import BeautifulSoup

from app.redis import get_redis

logger = logging.getLogger("alphareader.fetcher")

# ── 正则预过滤器：匹配到这些关键词的标题会被直接丢弃 ──
DROP_PATTERNS = re.compile(
    r"(推广|广告|赞助|课程|直播预告|星座|彩票|红包|优惠券|抽奖|免费领)", re.IGNORECASE
)

# Redis Set 的 key，存储所有已处理过的 URL 哈希值
REDIS_DEDUP_KEY = "alphareader:seen_urls"

# HTTP 请求头：模拟 Chrome 浏览器，避免被信源服务器拦截
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

# 触发切换到备用 URL 的 HTTP 状态码（429=限流，503=服务不可用）
_FALLBACK_STATUS_CODES = {429, 503}

# 解析器层面的时效性预过滤：丢弃 published_at 超过此天数的文章
# 某些 RSS 源（如 OpenAI Blog）返回全量历史，在解析器阶段就截断可减少下游处理量
_PARSER_MAX_AGE_DAYS = 8  # 比 pipeline 的 MAX_NEWS_AGE_DAYS(7) 多留 1 天余量


@dataclass
class RawNewsItem:
    """原始新闻条目——从信源抓取后、去重和评分之前的数据结构"""
    title: str
    content: str
    url: str
    source: str
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    # 事件聚合：当去重器判定为"同一事件的关联报道"时，记录更早报道的 URL
    related_to_url: str | None = None
    # 分类标签：科技 / 财经
    category: str = "财经"


def _normalize_url(url: str) -> str:
    """标准化 URL：去除尾部斜杠、去除常见 tracking 参数。
    
    解决同一篇文章因 URL 微小差异（如尾部 / 或 utm_ 参数）
    被 Redis 去重漏过的问题。
    例如：
      https://openai.com/index/xxx/  → https://openai.com/index/xxx
      https://example.com/a?utm_source=feed → https://example.com/a
    """
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    parsed = urlparse(url.strip())
    # 去除尾部斜杠（但保留根路径 /）
    path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path
    # 去除 tracking 查询参数
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {k: v for k, v in params.items()
                   if not k.startswith(("utm_", "feed_item"))}
        query = urlencode(cleaned, doseq=True) if cleaned else ""
    else:
        query = ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def _hash_url(url: str) -> str:
    """将标准化后的 URL 转为 SHA-256 哈希，用于 Redis 去重"""
    return hashlib.sha256(_normalize_url(url).encode()).hexdigest()


def _should_keep(title: str, source: str = "") -> bool:
    """标题预过滤：返回 True 表示保留，False 表示丢弃"""
    if not title or len(title.strip()) < 4:
        return False
    if DROP_PATTERNS.search(title):
        return False
    # 硬规则：财联社付费栏目标题一律丢弃
    # 常见付费栏目前缀：【研选】、【风口研报·公司】、【风口研报·行业】等
    if source == "财联社" and re.search(r"(研选|风口研报)", title):
        return False
    return True


def _cls_sign(params: dict) -> str:
    """财联社 v1 接口签名算法：MD5(SHA1(排序后的 ``k=v&...`` 串))。

    财联社 Web 端对每个请求做签名校验，未带正确 sign 的调用返回
    ``{"errno":10012,"msg":"签名错误"}``。算法逆向自 cls.cn 前端 JS 的请求层：

      1. 将除 sign 外的参数按 key 升序排列，拼成 ``k1=v1&k2=v2...``
      2. 对内层串取 SHA1 的十六进制摘要
      3. 再对 SHA1 摘要取 MD5 得到最终 sign

    注意：该接口此前历经多次改版（updateTelegraphList → telegraphList →
    v1/roll/get_roll_list），并引入签名校验。若将来再次失效，需重新核对
    cls.cn 前端 bundle 中的 ``_cls_sign`` 算法与 app/os/sv 版本号。
    """
    import hashlib

    raw = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    sha1 = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1.encode("utf-8")).hexdigest()


def _cls_build_params(rn: int = 30, last_time: int = 0) -> dict:
    """构造带签名的财联社 ``v1/roll/get_roll_list`` 请求参数。

    app/os/sv 为 Web 端固定标识；refresh_type=1 表示按时间倒序拉取最新电报；
    rn 为条数；last_time 用于分页（传入上一批最后一条的 ctime，首屏传 0）。
    """
    params = {
        "app": "CailianpressWeb",
        "os": "web",
        "sv": "8.7.9",
        "refresh_type": 1,
        "rn": rn,
        "last_time": last_time,
    }
    params["sign"] = _cls_sign(params)
    return params


# ════════════════════════════════════════════════════════════════
# 信源解析器（Source Adapters）
# 每个解析器负责将特定信源 API 返回的 JSON/XML 转换为 RawNewsItem 列表
# ════════════════════════════════════════════════════════════════

def _parse_cls(data: dict) -> list[RawNewsItem]:
    """解析财联社电报 API（cls.cn）

    接口近期从 updateTelegraphList 更名为 telegraphList，且不同版本返回结构有差异
    （数组可能位于 data.roll_data / data.telegraphList / data.list；单条字段可能为
    ctime/created_at/timestamp、id/aid、brief/content/description）。此处做多路径兼容。
    URL 格式: https://www.cls.cn/detail/{id}
    """
    items: list[RawNewsItem] = []
    if not isinstance(data, dict):
        return items
    payload = data.get("data", data)
    if not isinstance(payload, dict):
        payload = {}
    raw = (
        payload.get("roll_data")
        or payload.get("telegraphList")
        or payload.get("list")
        or data.get("roll_data")
        or []
    )
    if not isinstance(raw, list):
        return items
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or entry.get("brief") or "").strip()
        content = (
            entry.get("content")
            or entry.get("brief")
            or entry.get("description")
            or ""
        ).strip()
        aid = entry.get("id") or entry.get("aid") or ""
        url = f"https://www.cls.cn/detail/{aid}" if aid else (entry.get("url") or "")
        ts = entry.get("ctime") or entry.get("created_at") or entry.get("timestamp")
        try:
            published = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
        except (TypeError, ValueError):
            published = None

        if title and url:
            items.append(RawNewsItem(
                title=title, content=content,
                url=url, source="财联社", published_at=published,
            ))
    return items


def _parse_sina(data: dict) -> list[RawNewsItem]:
    """解析新浪财经滚动新闻 API
    数据路径: result.data[] → 取 title/url/intro/ctime/media_name
    """
    items: list[RawNewsItem] = []
    for entry in data.get("result", {}).get("data", []):
        title = entry.get("title", "")
        url = entry.get("url", "")
        content = entry.get("intro", "") or title
        ts_str = entry.get("ctime", "")
        published = None
        if ts_str:
            try:
                published = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        tags = []
        media = entry.get("media_name", "")
        if media:
            tags.append(media)
        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=content.strip(),
                url=url, source="新浪财经", published_at=published, tags=tags,
            ))
    return items


def _parse_wallstreetcn(data: dict) -> list[RawNewsItem]:
    """解析华尔街见闻实时快讯 API
    数据路径: data.items[] → 取 title/content_text/uri/display_time
    URL 格式: https://wallstreetcn.com/{uri}  (uri 已含完整路径，如 livenews/3066594)
    """
    items: list[RawNewsItem] = []
    for entry in data.get("data", {}).get("items", []):
        title = entry.get("title", "") or ""
        content_text = entry.get("content_text", "") or title
        uri = entry.get("uri", "")
        url = f"https://wallstreetcn.com/{uri}" if uri else ""
        ts = entry.get("display_time")
        published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        if not title and content_text:
            title = content_text[:60]
        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=content_text.strip(),
                url=url, source="华尔街见闻", published_at=published,
            ))
    return items


def _parse_10jqka(data: dict) -> list[RawNewsItem]:
    """Parse 同花顺 (10jqka) news API."""
    items: list[RawNewsItem] = []
    for entry in data.get("data", {}).get("list", []):
        title = entry.get("title", "")
        digest = entry.get("digest", "") or title
        nid = entry.get("id", "")
        url = f"https://news.10jqka.com.cn/{nid}" if nid else entry.get("url", "")
        ts_str = entry.get("time", "") or entry.get("ctime", "")
        published = None
        if ts_str:
            try:
                published = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
            except (ValueError, OSError):
                pass
        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=digest.strip(),
                url=url, source="同花顺", published_at=published,
            ))
    return items


def _parse_eastmoney_ann(data: dict) -> list[RawNewsItem]:
    """Parse 东方财富公告 API."""
    items: list[RawNewsItem] = []
    for entry in data.get("data", {}).get("list", []):
        title = entry.get("title", "") or ""
        art_code = entry.get("art_code", "")
        url = f"https://data.eastmoney.com/notices/detail/{art_code}.html" if art_code else ""
        ts_str = entry.get("display_time", "")
        published = None
        if ts_str:
            try:
                published = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        # Extract stock names as tags
        tags = []
        for code_info in entry.get("codes", []):
            name = code_info.get("short_name", "")
            if name:
                tags.append(name)
        content = f"{title} - {', '.join(tags)}" if tags else title
        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=content.strip(),
                url=url, source="东方财富", published_at=published, tags=tags,
            ))
    return items


def _parse_eastmoney_kuaixun(data: dict) -> list[RawNewsItem]:
    """Parse 东方财富快讯 API."""
    items: list[RawNewsItem] = []
    for entry in data.get("data", {}).get("list", []):
        title = entry.get("title", "") or ""
        summary = entry.get("summary", "") or title
        code = entry.get("code", "")
        unique_url = entry.get("uniqueUrl", "")
        url = unique_url or (f"https://kuaixun.eastmoney.com/ssgs/{code}.html" if code else "")
        ts_str = entry.get("showTime", "")
        published = None
        if ts_str:
            try:
                published = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        # Use summary as both title and content if title is empty
        if not title and summary:
            title = summary[:80]
        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=summary.strip(),
                url=url, source="东方财富快讯", published_at=published,
            ))
    return items


def _parse_yicai(data: list | dict) -> list[RawNewsItem]:
    """Parse 第一财经 latest API (returns a JSON array directly)."""
    items: list[RawNewsItem] = []
    entries = data if isinstance(data, list) else data.get("data", [])
    for entry in entries:
        title = entry.get("NewsTitle", "") or entry.get("Title", "") or ""
        news_id = entry.get("NewsID", "") or entry.get("EntityNews", "")
        url = f"https://www.yicai.com/news/{news_id}.html" if news_id else ""
        content = entry.get("NewsAbstract", "") or entry.get("Hl", "") or title
        ts_str = entry.get("CreateDate", "") or entry.get("PublishDate", "")
        published = None
        if ts_str:
            try:
                published = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        channel = entry.get("ChannelName", "")
        tags = [channel] if channel else []
        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=content.strip(),
                url=url, source="第一财经", published_at=published, tags=tags,
            ))
    return items


# ════════════════════════════════════════════════════════════════
# 国际信源解析器 — 通过 feedparser 解析 RSS/Atom XML
# ════════════════════════════════════════════════════════════════

def _strip_html(text: str) -> str:
    """用 BeautifulSoup 去除 HTML 标签，返回纯文本"""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _parse_rss_time(entry: dict) -> datetime | None:
    """从 feedparser 条目中提取发布时间，转换为 UTC datetime"""
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if ts:
        try:
            from calendar import timegm
            return datetime.fromtimestamp(timegm(ts), tz=timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None


def _parse_marketwatch(raw_text: str) -> list[RawNewsItem]:
    """Parse MarketWatch Top Stories RSS feed."""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="MarketWatch", published_at=published,
            ))
    return items


def _parse_cnbc(raw_text: str) -> list[RawNewsItem]:
    """Parse CNBC RSS feed (World / US Markets)."""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="CNBC", published_at=published,
            ))
    return items


def _parse_seekingalpha(raw_text: str) -> list[RawNewsItem]:
    """Parse Seeking Alpha Market Currents RSS feed."""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="Seeking Alpha", published_at=published, tags=tags[:3],
            ))
    return items


def _parse_techcrunch(raw_text: str) -> list[RawNewsItem]:
    """Parse TechCrunch RSS feed."""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="TechCrunch", published_at=published, tags=tags[:3],
                category="科技",
            ))
    return items


def _parse_finnhub(data: list | dict) -> list[RawNewsItem]:
    """解析 Finnhub Market News API（https://finnhub.io/api/v1/news）

    返回 JSON 数组，每条包含:
      headline, summary, url, source, datetime(unix), related, category, id
    """
    items: list[RawNewsItem] = []
    entries = data if isinstance(data, list) else []
    for entry in entries:
        title = (entry.get("headline") or "").strip()
        url = entry.get("url", "")
        summary = (entry.get("summary") or "").strip()
        content = summary or title
        ts = entry.get("datetime")
        published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        # related 字段包含相关股票代码，如 "AAPL,MSFT"
        related = entry.get("related", "")
        tags = [t.strip() for t in related.split(",") if t.strip()] if related else []
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content,
                url=url, source="Finnhub", published_at=published, tags=tags[:5],
            ))
    return items


# ════════════════════════════════════════════════════════════════
# 科技信源解析器 — AI/Tech Blog RSS + Hacker News Firebase API
# ════════════════════════════════════════════════════════════════

def _extract_year_from_url(url: str) -> int | None:
    """从 URL 路径中提取文章发布年份。

    许多博客/新闻站点的 URL 包含年份，例如：
      https://openai.com/blog/better-language-models/  → 无法提取
      https://example.com/2019/02/14/some-article       → 2019
      https://example.com/blog/2021-03-new-feature      → 2021
    返回 None 表示无法从 URL 判断年份。
    """
    # 匹配 URL 路径中的 4 位年份（/2019/、/2019-、2019_ 等边界）
    m = re.search(r'(?:^|[/\-_.])(\d{4})(?:[/\-_.]|$)', url)
    if m:
        year = int(m.group(1))
        # 只认 2000-2099 范围内的合理年份
        if 2000 <= year <= 2099:
            return year
    return None


def _parse_hackernews(data: list | dict) -> list[RawNewsItem]:
    """解析 Hacker News Algolia API（https://hn.algolia.com/api/v1/search）

    使用 Algolia 搜索 API 替代 Firebase API，一次请求即可获取所有热门文章，
    避免从中国服务器逐条请求 Firebase 的高延迟和高失败率。

    注意：Algolia API 的 created_at_i 是文章在 HN 上被提交的时间，不是原始文章
    的发布日期。老文章被重新提交到 HN 时 created_at_i 是当天，会绕过 stale filter。
    因此额外通过 URL 中的年份做二次校验，丢弃明确过旧的文章。
    """
    items: list[RawNewsItem] = []
    now_year = datetime.now(timezone.utc).year
    # 允许的最大年龄：URL 中的年份距今超过此值则丢弃
    max_url_age_years = 1
    skipped_old = 0

    # Algolia API 返回 {"hits": [...]}
    entries = data.get("hits", []) if isinstance(data, dict) else data
    for entry in entries:
        title = (entry.get("title") or "").strip()
        url = entry.get("url") or f"https://news.ycombinator.com/item?id={entry.get('objectID', '')}"

        # ── 二次校验：从文章 URL 提取年份，丢弃明确过旧的文章 ──
        url_year = _extract_year_from_url(url)
        if url_year and (now_year - url_year) > max_url_age_years:
            skipped_old += 1
            logger.debug(
                "HN: skip old article (url_year=%d, age=%d yr): %s",
                url_year, now_year - url_year, title,
            )
            continue

        # Algolia 使用 created_at_i (unix timestamp)
        # 注意：这是 HN 提交时间，不是原始文章发布时间
        ts = entry.get("created_at_i") or entry.get("time")
        published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        if title:
            items.append(RawNewsItem(
                title=title, content=title,
                url=url, source="Hacker News", published_at=published,
                category="科技",
            ))

    if skipped_old:
        logger.info("HN parser: skipped %d old articles based on URL year", skipped_old)
    return items


def _parse_openai_blog(raw_text: str) -> list[RawNewsItem]:
    """解析 OpenAI Blog RSS (https://openai.com/news/rss/)
    
    注意：OpenAI Blog RSS 会返回全量历史文章（~900条，从2016年至今），
    必须在解析器内部预过滤，只保留最近 _PARSER_MAX_AGE_DAYS 天的文章，
    避免下游浪费大量 Redis 查询和内存。
    """
    from datetime import timedelta
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_PARSER_MAX_AGE_DAYS)
    skipped = 0
    for entry in feed.entries:
        published = _parse_rss_time(entry)
        # 有明确发布时间且超过截止日期的直接跳过
        if published and published < cutoff:
            skipped += 1
            continue
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="OpenAI Blog", published_at=published,
                category="科技",
            ))
    if skipped:
        logger.info("OpenAI Blog: pre-filtered %d stale entries (>%dd), kept %d",
                     skipped, _PARSER_MAX_AGE_DAYS, len(items))
    return items


def _parse_google_ai_blog(raw_text: str) -> list[RawNewsItem]:
    """解析 Google AI Blog RSS (https://blog.google/technology/ai/rss/)"""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="Google AI Blog", published_at=published,
                category="科技",
            ))
    return items


def _parse_anthropic(raw_text: str) -> list[RawNewsItem]:
    """解析 Anthropic sitemap.xml，提取 /engineering/ + /research/ + /news/ 下的文章。

    Anthropic 没有 RSS feed，但 sitemap.xml 包含所有文章 URL 和 lastmod 时间。
    我们从中筛选最近的文章条目。
    """
    import xml.etree.ElementTree as ET

    items: list[RawNewsItem] = []
    try:
        root = ET.fromstring(raw_text)
    except ET.ParseError:
        return items

    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    prefixes = ("/engineering/", "/research/", "/news/")

    for url_elem in root.findall("s:url", ns):
        loc = (url_elem.findtext("s:loc", "", ns) or "").strip()
        lastmod = (url_elem.findtext("s:lastmod", "", ns) or "").strip()

        # 只要 engineering / research / news 下的子页面
        from urllib.parse import urlparse
        path = urlparse(loc).path
        if not any(path.startswith(p) for p in prefixes):
            continue
        # 排除分类首页（如 /engineering/ 本身）
        slug = path.rstrip("/").split("/")[-1]
        if not slug or slug in ("engineering", "research", "news"):
            continue

        # 从 slug 生成标题（将连字符替换为空格）
        # 使用 capitalize 而非 title()，避免将缩写词 RL/AI 错误地变成 Rl/Ai
        raw_title = slug.replace("-", " ")
        title = raw_title[0].upper() + raw_title[1:] if raw_title else raw_title

        published = None
        if lastmod:
            try:
                from datetime import datetime, timezone
                # sitemap lastmod 格式通常是 YYYY-MM-DD 或 ISO 8601
                if "T" in lastmod:
                    published = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
                else:
                    published = datetime.strptime(lastmod, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass

        items.append(RawNewsItem(
            title=title, content=title,
            url=loc, source="Anthropic", published_at=published,
            category="科技",
        ))

    # 按 lastmod 降序排列，只取最近 30 条
    items.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:30]


def _parse_huggingface_blog(raw_text: str) -> list[RawNewsItem]:
    """解析 Hugging Face Blog RSS (https://huggingface.co/blog/feed.xml)"""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="Hugging Face", published_at=published, tags=tags[:3],
                category="科技",
            ))
    return items


def _parse_mit_tech_review(raw_text: str) -> list[RawNewsItem]:
    """解析 MIT Technology Review RSS (https://www.technologyreview.com/feed/)"""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="MIT Tech Review", published_at=published, tags=tags[:3],
                category="科技",
            ))
    return items


def _generic_rss_parse(
    raw_text: str, source_name: str, category: str = "财经",
) -> list[RawNewsItem]:
    """通用 RSS/Atom 解析器：用 feedparser 解析结构标准的 RSS 源。

    适用于标题/链接/摘要均挂在 entry 标准字段上的信源。
    新增标准 RSS 信源时，优先复用本函数，避免重复样板代码。
    """
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)
        tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source=source_name, published_at=published,
                tags=tags[:3], category=category,
            ))
    return items


# ── 新增科技信源（标准 RSS，复用 _generic_rss_parse）──
def _parse_marktechpost(raw_text: str) -> list[RawNewsItem]:
    """Parse MarkTechPost RSS (https://www.marktechpost.com/feed/)."""
    return _generic_rss_parse(raw_text, source_name="MarkTechPost", category="科技")


def _parse_arxiv_ai(raw_text: str) -> list[RawNewsItem]:
    """Parse arXiv cs.AI RSS (https://rss.arxiv.org/rss/cs.AI)."""
    return _generic_rss_parse(raw_text, source_name="arXiv cs.AI", category="科技")


def _parse_arxiv_cl(raw_text: str) -> list[RawNewsItem]:
    """Parse arXiv cs.CL RSS (https://rss.arxiv.org/rss/cs.CL)."""
    return _generic_rss_parse(raw_text, source_name="arXiv cs.CL", category="科技")


def _parse_theverge_ai(raw_text: str) -> list[RawNewsItem]:
    """Parse The Verge AI RSS (https://www.theverge.com/rss/ai-artificial-intelligence/index.xml)."""
    return _generic_rss_parse(raw_text, source_name="The Verge AI", category="科技")


def _parse_lastweekin_ai(raw_text: str) -> list[RawNewsItem]:
    """Parse Last Week in AI RSS (https://lastweekin.ai/feed)."""
    return _generic_rss_parse(raw_text, source_name="Last Week in AI", category="科技")


def _parse_gradient(raw_text: str) -> list[RawNewsItem]:
    """Parse The Gradient RSS (https://thegradient.pub/rss/)."""
    return _generic_rss_parse(raw_text, source_name="The Gradient", category="科技")


def _parse_nvidia_blog(raw_text: str) -> list[RawNewsItem]:
    """Parse NVIDIA Blog RSS (https://blogs.nvidia.com/feed/)."""
    return _generic_rss_parse(raw_text, source_name="NVIDIA Blog", category="科技")


def _parse_simonwillison(raw_text: str) -> list[RawNewsItem]:
    """Parse Simon Willison Atom feed (https://simonwillison.net/atom/everything/)."""
    return _generic_rss_parse(raw_text, source_name="Simon Willison", category="科技")


# ── 新增财经信源（标准 RSS，复用 _generic_rss_parse）──
def _parse_investinglive(raw_text: str) -> list[RawNewsItem]:
    """Parse Investing.com / investinglive market RSS (https://investinglive.com/rss/)."""
    return _generic_rss_parse(raw_text, source_name="Investing.com", category="财经")


def _parse_reuters(raw_text: str) -> list[RawNewsItem]:
    """Parse Reuters news feed (via RSSHub, e.g. /reuters/world/us)."""
    return _generic_rss_parse(raw_text, source_name="Reuters", category="财经")


def _parse_yahoo_finance(raw_text: str) -> list[RawNewsItem]:
    """Parse Yahoo Finance news feed (via RSSHub, e.g. /yahoo/finance/news)."""
    return _generic_rss_parse(raw_text, source_name="Yahoo Finance", category="财经")


def _parse_sec_edgar(raw_text: str) -> list[RawNewsItem]:
    """解析 SEC EDGAR Latest Filings Atom feed。

    URL: https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom

    条目结构（Atom）：
      title  = "8-K - Company Name (CIK) (Filer)"
      link   = 指向该 filing 的 -index.htm
      summary= HTML 片段，含 "Filed: YYYY-MM-DD" 和 AccNo
      updated= filing 接收时间

    注意：SEC 要求请求方 UA 带联系邮箱（在 FeedSource.extra_headers 配置）。
    """
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        summary = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        published = _parse_rss_time(entry)

        # 从 title 中提取 form type（8-K/10-K/...）与公司名作为标签
        tags: list[str] = []
        m = re.match(r"^([A-Z0-9\-/]+)\s*-\s*(.+?)\s*\(\d+\)\s*\(Filer\)\s*$", title)
        if m:
            form_type, company = m.group(1), m.group(2).strip()
            tags = [form_type, company]

        if title and url:
            items.append(RawNewsItem(
                title=title, content=summary or title,
                url=url, source="SEC EDGAR", published_at=published,
                tags=tags[:3], category="财经",
            ))
    return items


@dataclass
class FeedSource:
    """信源配置：name=信源名称，url=API地址，parser=对应解析函数，is_rss=是否RSS格式"""
    name: str
    url: str                                    # 主 URL
    parser: Callable
    is_rss: bool = False                        # True = RSS/Atom 格式，用 feedparser 解析
    fallback_urls: list[str] = field(default_factory=list)  # 主 URL 失败时按顺序尝试的备用 URL
    extra_headers: dict[str, str] = field(default_factory=dict)  # 追加到该源 HTTP 请求的自定义头（覆盖 HTTP_HEADERS）
    signed_cls: bool = False                    # True = 财联社 v1 接口，需动态计算签名后作为 query 参数发送


# RSSHub 备用实例列表（可通过环境变量 RSSHUB_INSTANCES 覆盖，逗号分隔）
# RSSHub 是开源的 RSS 生成器，提供多个公共实例作为备用
# 注意：必须在 FEED_SOURCES 之前定义，因为部分信源的 fallback_urls 引用此列表
import os as _os
_RSSHUB_INSTANCES = [
    u.strip() for u in
    _os.environ.get("RSSHUB_INSTANCES", "").split(",")
    if u.strip()
] or [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub.pseudoyu.com",
]


# 活跃信源列表：pipeline 每次运行时并发抓取以下所有信源
FEED_SOURCES: list[FeedSource] = [
    # ── 财经信源 ──
    FeedSource(
        name="富途新闻",
        # 富途快讯接口，无需签名，需带 Referer
        url="https://news.futunn.com/news-site-api/main/get-flash-list?pageSize=30&lastTime=0",
        extra_headers={
            **HTTP_HEADERS,
            "Referer": "https://news.futunn.com/main/live",
        },
        parser=_parse_futu,
    ),
    # 华尔街见闻已移除（2026-03-09，内容与财联社高度重叠）
    # 财联社已移除（2026-07-13，电报流含大量 A 股个股异动/盘面快讯噪音，替换为富途新闻快讯）


def _parse_futu(data: dict) -> list[RawNewsItem]:
    """解析富途新闻快讯 API（news.futunn.com）

    接口: https://news.futunn.com/news-site-api/main/get-flash-list
    参数: pageSize（条数，支持 30+）, lastTime（分页时间戳，0=最新一页）

    返回结构: data.data.news[] → 取 title/content/detailUrl/time/relatedStocks

    富途快讯以宏观政策、市场要闻为主，相比财联社电报的 A 股个股异动噪音更少。
    部分快讯 title 为空，此时用 content 前 60 字作为标题。
    """
    items: list[RawNewsItem] = []
    if not isinstance(data, dict):
        return items
    news_list = data.get("data", {}).get("data", {}).get("news", [])
    if not isinstance(news_list, list):
        return items
    for entry in news_list:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or "").strip()
        content = (entry.get("content") or "").strip()
        if not title and content:
            title = content[:60]
        url = entry.get("detailUrl", "")
        ts = entry.get("time")
        published = None
        if ts:
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (TypeError, ValueError):
                pass
        # relatedStocks 可能包含关联个股
        tags: list[str] = []
        for stock in entry.get("relatedStocks", []):
            if isinstance(stock, dict):
                name = stock.get("stock_name", "") or stock.get("name", "")
                if name:
                    tags.append(name)
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="富途新闻", published_at=published,
                tags=tags[:5],
            ))
    return items
    # ── International Sources (RSS/Atom XML) ──
    FeedSource(
        name="MarketWatch",
        url="https://feeds.marketwatch.com/marketwatch/topstories/",
        parser=_parse_marketwatch,
        is_rss=True,
    ),
    FeedSource(
        name="Seeking Alpha",
        url="https://seekingalpha.com/market_currents.xml",
        parser=_parse_seekingalpha,
        is_rss=True,
    ),
    FeedSource(
        name="CNBC",
        url="https://www.cnbc.com/id/100003114/device/rss/rss.html",
        parser=_parse_cnbc,
        is_rss=True,
    ),
    FeedSource(
        name="Investing.com",
        url="https://www.investing.com/rss/news_25.rss",
        parser=_parse_investinglive,
        is_rss=True,
    ),
    # Reuters / Yahoo Finance 无原生 RSS，改用 Google News RSS 按站点过滤
    # （稳定、无需第三方 RSSHub 实例；标题会带 " - Reuters" 后缀，内容为标准 RSS 摘要）
    FeedSource(
        name="Reuters",
        url="https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en",
        parser=_parse_reuters,
        is_rss=True,
    ),
    FeedSource(
        name="Yahoo Finance",
        url="https://news.google.com/rss/search?q=site:finance.yahoo.com&hl=en-US&gl=US&ceid=US:en",
        parser=_parse_yahoo_finance,
        is_rss=True,
    ),
    # SEC EDGAR: 一手 8-K filing 流。UA 必须带联系邮箱（extra_headers 动态注入见 fetch_all_feeds）
    FeedSource(
        name="SEC EDGAR",
        url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=40&output=atom",
        parser=_parse_sec_edgar,
        is_rss=True,
    ),
    FeedSource(
        name="Finnhub",
        url="",  # 动态构建，见 fetch_all_feeds()
        parser=_parse_finnhub,
    ),
    # ── 科技信源 ──
    FeedSource(
        name="TechCrunch",
        url="https://techcrunch.com/feed/",
        parser=_parse_techcrunch,
        is_rss=True,
        fallback_urls=[
            f"{inst}/techcrunch" for inst in _RSSHUB_INSTANCES
        ],
    ),
    FeedSource(
        name="Hacker News",
        url="https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30",
        parser=_parse_hackernews,
        # 使用 Algolia API 替代 Firebase，一次请求获取所有热门文章
        # 避免从中国服务器多次请求 Firebase 的高延迟和高失败率
    ),
    FeedSource(
        name="OpenAI Blog",
        url="https://openai.com/news/rss.xml",
        parser=_parse_openai_blog,
        is_rss=True,
    ),
    FeedSource(
        name="Google AI Blog",
        url="https://blog.google/technology/ai/rss/",
        parser=_parse_google_ai_blog,
        is_rss=True,
        fallback_urls=[
            f"{inst}/google/blog/ai" for inst in _RSSHUB_INSTANCES
        ],
    ),
    FeedSource(
        name="Anthropic",
        url="https://www.anthropic.com/sitemap.xml",
        parser=_parse_anthropic,
        is_rss=True,  # 将 raw text 传给 parser（内部用 XML 解析 sitemap）
    ),
    FeedSource(
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        parser=_parse_huggingface_blog,
        is_rss=True,
        fallback_urls=[
            f"{inst}/huggingface/blog" for inst in _RSSHUB_INSTANCES
        ],
    ),
    FeedSource(
        name="MIT Tech Review",
        url="https://www.technologyreview.com/feed/",
        parser=_parse_mit_tech_review,
        is_rss=True,
    ),
    # ── 新增科技信源（2026-07-08）──
    FeedSource(
        name="MarkTechPost",
        url="https://www.marktechpost.com/feed/",
        parser=_parse_marktechpost,
        is_rss=True,
        fallback_urls=[
            f"{inst}/marktechpost" for inst in _RSSHUB_INSTANCES
        ],
    ),
    FeedSource(
        name="arXiv cs.AI",
        url="https://rss.arxiv.org/rss/cs.AI",
        parser=_parse_arxiv_ai,
        is_rss=True,
    ),
    FeedSource(
        name="arXiv cs.CL",
        url="https://rss.arxiv.org/rss/cs.CL",
        parser=_parse_arxiv_cl,
        is_rss=True,
    ),
    FeedSource(
        name="The Verge AI",
        url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        parser=_parse_theverge_ai,
        is_rss=True,
        fallback_urls=[
            f"{inst}/theverge" for inst in _RSSHUB_INSTANCES
        ],
    ),
    FeedSource(
        name="Last Week in AI",
        url="https://lastweekin.ai/feed",
        parser=_parse_lastweekin_ai,
        is_rss=True,
    ),
    FeedSource(
        name="The Gradient",
        url="https://thegradient.pub/rss/",
        parser=_parse_gradient,
        is_rss=True,
    ),
    FeedSource(
        name="NVIDIA Blog",
        url="https://blogs.nvidia.com/feed/",
        parser=_parse_nvidia_blog,
        is_rss=True,
    ),
    FeedSource(
        name="Simon Willison",
        url="https://simonwillison.net/atom/everything/",
        parser=_parse_simonwillison,
        is_rss=True,
    ),
]

# 指数退避重试配置：每个 URL 最多重试 2 次，等待时间 = 2 × 2^attempt 秒
_BACKOFF_MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 2


# ════════════════════════════════════════════════════════
# 核心抓取逻辑
# ════════════════════════════════════════════════════════

async def _fetch_single_source(
    client: httpx.AsyncClient,
    source: FeedSource,
    r: aioredis.Redis,
) -> list[RawNewsItem]:
    """抓取并解析单个信源，同时通过 Redis 过滤已处理过的 URL。

    错误隔离：所有异常被捕获，确保单个信源的失败不会影响整个 pipeline。
    注意：这里只检查 URL 是否已见过，不标记——标记在 pipeline 存储成功后才执行。
    """
    items: list[RawNewsItem] = []

    try:
        raw_items = await _fetch_raw_items(client, source)
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", source.name, e)
        return items

    if raw_items is None:
        return items

    logger.info("Parsed %d raw items from %s", len(raw_items), source.name)

    for item in raw_items:
        if not item.url:
            continue

        url_hash = _hash_url(item.url)

        # Check if URL was already seen — do NOT mark as seen here.
        # URLs are only marked after successful storage in the pipeline.
        try:
            is_seen = await r.sismember(REDIS_DEDUP_KEY, url_hash)
        except Exception as e:
            logger.warning("Redis SISMEMBER failed for %s, treating as new: %s", item.url[:60], e)
            is_seen = False

        if is_seen:
            continue

        if not _should_keep(item.title, item.source):
            logger.debug("Dropped by regex: %s", item.title)
            continue

        items.append(item)

    logger.info("After dedup+filter: %d new items from %s", len(items), source.name)
    return items


async def _fetch_raw_items(
    client: httpx.AsyncClient,
    source: FeedSource,
) -> list[RawNewsItem] | None:
    """抓取单个信源的原始数据并解析。失败返回 None。

    如果信源配置了 fallback_urls，会使用 Primary → Fallback 策略逐个尝试。
    """
    if source.fallback_urls:
        return await _fetch_with_fallback(client, source)

    # 财联社 v1 接口需动态计算签名，并以 query 参数形式随请求发送
    if source.signed_cls:
        params = _cls_build_params()
        try:
            resp = await client.get(
                source.url, params=params, timeout=20.0,
                headers=source.extra_headers or None,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", source.name, e)
            return None
        try:
            return source.parser(resp.json())
        except Exception as e:
            logger.error("Parser error for %s: %s", source.name, e)
            return None

    try:
        resp = await client.get(
            source.url, timeout=20.0,
            headers=source.extra_headers or None,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", source.name, e)
        return None

    try:
        if source.is_rss:
            return source.parser(resp.text)
        else:
            return source.parser(resp.json())
    except Exception as e:
        logger.error("Parser error for %s: %s", source.name, e)
        return None


async def _fetch_with_fallback(
    client: httpx.AsyncClient,
    source: FeedSource,
) -> list[RawNewsItem] | None:
    """带备用 URL 的抓取：Primary → Fallback，每个 URL 支持指数退避重试。

    策略：
    - 429/503 → 指数退避重试（最多 _BACKOFF_MAX_RETRIES 次）
    - 成功 → 解析并返回
    - 其他错误 → 跳到下一个 URL
    - 所有 URL 都失败 → 返回 None
    """
    all_urls = [source.url] + source.fallback_urls

    for url_idx, url in enumerate(all_urls):
        label = "primary" if url_idx == 0 else f"fallback-{url_idx}"

        for attempt in range(_BACKOFF_MAX_RETRIES + 1):
            try:
                resp = await client.get(
                    url, timeout=20.0,
                    headers=source.extra_headers or None,
                )
                resp.raise_for_status()

                # Success — parse and return
                logger.info(
                    "%s fetched via %s (%s)", source.name, url[:60], label,
                )
                try:
                    if source.is_rss:
                        return source.parser(resp.text)
                    else:
                        return source.parser(resp.json())
                except Exception as e:
                    logger.error("Parser error for %s (%s): %s", source.name, url[:60], e)
                    return None

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if status in _FALLBACK_STATUS_CODES and attempt < _BACKOFF_MAX_RETRIES:
                    wait = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                    logger.warning(
                        "%s %s returned %d (attempt %d/%d), retrying in %ds...",
                        source.name, label, status,
                        attempt + 1, _BACKOFF_MAX_RETRIES + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Exhausted retries or non-fallback status — move to next URL
                if status in _FALLBACK_STATUS_CODES and url_idx < len(all_urls) - 1:
                    logger.warning(
                        "⚠️ %s %s rate-limited (%d), switching to next fallback URL...",
                        source.name, label, status,
                    )
                else:
                    logger.warning(
                        "%s %s failed: HTTP %d", source.name, label, status,
                    )
                break  # move to next URL

            except Exception as e:
                logger.warning("%s %s failed: %s", source.name, label, e)
                break  # move to next URL

    logger.warning("All URLs exhausted for %s — no data fetched", source.name)
    return None


@dataclass
class FetchResult:
    """抓取阶段的返回结果，包含各信源的统计信息。"""
    items: list[RawNewsItem]
    by_source: dict[str, int]  # {信源名: 抓取条数}


async def fetch_all_feeds() -> FetchResult:
    """并发抓取所有信源，返回去重后的新闻列表及各信源统计。这是抓取阶段的唯一入口。"""
    from app.config import settings

    r = get_redis()

    # 动态注入需要 API Key 的信源 URL
    for src in FEED_SOURCES:
        if src.name == "Finnhub" and not src.url:
            key = settings.FINNHUB_API_KEY
            if key:
                src.url = f"https://finnhub.io/api/v1/news?category=general&token={key}"
            else:
                logger.warning("FINNHUB_API_KEY not set, skipping Finnhub source")
        elif src.name == "SEC EDGAR" and not src.extra_headers:
            # SEC 强制要求 UA 带联系邮箱，否则返回 403
            # 参考: https://www.sec.gov/os/accessing-edgar-data
            email = settings.SEC_CONTACT_EMAIL
            src.extra_headers = {
                "User-Agent": f"AlphaReader Research {email}",
                "Accept": "application/atom+xml, application/xml",
            }

    active_sources = [s for s in FEED_SOURCES if s.url]

    async with httpx.AsyncClient(
        headers=HTTP_HEADERS,
        follow_redirects=True,
    ) as client:
        tasks = [
            _fetch_single_source(client, source, r)
            for source in active_sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items: list[RawNewsItem] = []
    by_source: dict[str, int] = {}
    for source, result in zip(active_sources, results):
        if isinstance(result, list):
            all_items.extend(result)
            by_source[source.name] = len(result)
        else:
            logger.error("Feed task error (%s): %s", source.name, result)
            by_source[source.name] = 0

    logger.info("Total new items across all sources: %d", len(all_items))
    return FetchResult(items=all_items, by_source=by_source)
