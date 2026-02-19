"""新闻抓取服务 (rss_fetcher.py)
=================================
职责：从多个中英文金融信源并发抓取新闻，返回去重后的原始新闻列表。

当前活跃信源（9 个）：
  中文：财联社 / 新浪财经 / 华尔街见闻（通过 JSON API）
  英文：MarketWatch / CNBC World / CNBC US Markets / Seeking Alpha / TechCrunch（通过 RSS/Atom XML）
        Finnhub（通过 JSON API，需 API Key）

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


@dataclass
class RawNewsItem:
    """原始新闻条目——从信源抓取后、去重和评分之前的数据结构"""
    title: str
    content: str
    url: str
    source: str
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)


def _hash_url(url: str) -> str:
    """将 URL 转为 SHA-256 哈希，用于 Redis 去重"""
    return hashlib.sha256(url.encode()).hexdigest()


def _should_keep(title: str, source: str = "") -> bool:
    """标题预过滤：返回 True 表示保留，False 表示丢弃"""
    if not title or len(title.strip()) < 4:
        return False
    if DROP_PATTERNS.search(title):
        return False
    # 硬规则：财联社【研选】新闻一律丢弃
    if source == "财联社" and "研选" in title:
        return False
    return True


# ════════════════════════════════════════════════════════════════
# 信源解析器（Source Adapters）
# 每个解析器负责将特定信源 API 返回的 JSON/XML 转换为 RawNewsItem 列表
# ════════════════════════════════════════════════════════════════

def _parse_cls(data: dict) -> list[RawNewsItem]:
    """解析财联社电报 API（cls.cn）
    数据路径: data.roll_data[] → 取 title/brief/content/ctime
    URL 格式: https://www.cls.cn/detail/{id}
    """
    items: list[RawNewsItem] = []
    for entry in data.get("data", {}).get("roll_data", []):
        title = entry.get("title", "") or entry.get("brief", "") or ""
        content = entry.get("content", "") or entry.get("brief", "") or ""
        aid = entry.get("id", "")
        url = f"https://www.cls.cn/detail/{aid}" if aid else ""
        ts = entry.get("ctime")
        published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None

        if title and url:
            items.append(RawNewsItem(
                title=title.strip(), content=content.strip(),
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
    URL 格式: https://wallstreetcn.com/live/{uri}
    """
    items: list[RawNewsItem] = []
    for entry in data.get("data", {}).get("items", []):
        title = entry.get("title", "") or ""
        content_text = entry.get("content_text", "") or title
        uri = entry.get("uri", "")
        url = f"https://wallstreetcn.com/live/{uri}" if uri else ""
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



# ════════════════════════════════════════════════════════
# 信源注册表 — 所有活跃信源的配置中心
# ════════════════════════════════════════════════════════

@dataclass
class FeedSource:
    """信源配置：name=信源名称，url=API地址，parser=对应解析函数，is_rss=是否RSS格式"""
    name: str
    url: str                                    # 主 URL
    parser: Callable
    is_rss: bool = False                        # True = RSS/Atom 格式，用 feedparser 解析
    fallback_urls: list[str] = field(default_factory=list)  # 主 URL 失败时按顺序尝试的备用 URL


# 活跃信源列表：pipeline 每次运行时并发抓取以下所有信源
FEED_SOURCES: list[FeedSource] = [
    FeedSource(
        name="财联社",
        url="https://www.cls.cn/nodeapi/updateTelegraphList?app=CailianpressWeb&os=web&sv=8.4.6&rn=30",
        parser=_parse_cls,
    ),
    FeedSource(
        name="新浪财经",
        url="https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=30&page=1",
        parser=_parse_sina,
    ),
    FeedSource(
        name="华尔街见闻",
        url="https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=30",
        parser=_parse_wallstreetcn,
    ),
    # 同花顺、东方财富公告、东方财富快讯、第一财经 已移除（2026-02-11）
    # 新浪财经、CNBC World、CNBC US Markets 已移除（2026-02-19）
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
        name="TechCrunch",
        url="https://techcrunch.com/feed/",
        parser=_parse_techcrunch,
        is_rss=True,
    ),
    FeedSource(
        name="Finnhub",
        url="",  # 动态构建，见 fetch_all_feeds()
        parser=_parse_finnhub,
    ),
]

# RSSHub 备用实例列表（可通过环境变量 RSSHUB_INSTANCES 覆盖，逗号分隔）
# RSSHub 是开源的 RSS 生成器，提供多个公共实例作为备用
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

    try:
        resp = await client.get(source.url, timeout=20.0)
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
                resp = await client.get(url, timeout=20.0)
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


async def fetch_all_feeds() -> list[RawNewsItem]:
    """并发抓取所有信源，返回去重后的新闻列表。这是抓取阶段的唯一入口。"""
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
    for result in results:
        if isinstance(result, list):
            all_items.extend(result)
        else:
            logger.error("Feed task error: %s", result)

    logger.info("Total new items across all sources: %d", len(all_items))
    return all_items
