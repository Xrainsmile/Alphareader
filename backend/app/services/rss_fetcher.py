"""News Fetcher Service — async fetch from Chinese + International financial sources.

Supports 12 data sources:
  Chinese:  财联社 / 新浪财经 / 华尔街见闻 / 同花顺 / 东方财富(公告) / 东方财富(快讯) / 第一财经
  Global:   Reuters / CNBC / Seeking Alpha / TechCrunch / X(@DeItaone)

Flow:
  1. Iterate configured sources concurrently via httpx.
  2. Parse each source's unique JSON/XML structure via adapters.
  3. Dedup against Redis set (url hash).
  4. Apply regex pre-filter (drop spam).
  5. Return list of RawNewsItem for downstream DeepSeek scoring.
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

# ── Regex Pre-filters ──
DROP_PATTERNS = re.compile(
    r"(推广|广告|赞助|课程|直播预告|星座|彩票|红包|优惠券|抽奖|免费领)", re.IGNORECASE
)

REDIS_DEDUP_KEY = "alphareader:seen_urls"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


@dataclass
class RawNewsItem:
    """Unprocessed news item from any source."""
    title: str
    content: str
    url: str
    source: str
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _should_keep(title: str, source: str = "") -> bool:
    """Return True if the title passes the regex pre-filter."""
    if not title or len(title.strip()) < 4:
        return False
    if DROP_PATTERNS.search(title):
        return False
    # 硬规则：财联社【研选】新闻一律丢弃
    if source == "财联社" and "研选" in title:
        return False
    return True


# ════════════════════════════════════════════════════════════════
# Source Adapters — each parses a specific API's JSON into items
# ════════════════════════════════════════════════════════════════

def _parse_cls(data: dict) -> list[RawNewsItem]:
    """Parse 财联社 (cls.cn) telegraph API."""
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
    """Parse 新浪财经 roll API."""
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
    """Parse 华尔街见闻 lives API."""
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
# International Source Adapters — parse RSS/Atom XML via feedparser
# ════════════════════════════════════════════════════════════════

def _strip_html(text: str) -> str:
    """Strip HTML tags from text, returning plain text."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _parse_rss_time(entry: dict) -> datetime | None:
    """Extract published time from a feedparser entry."""
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if ts:
        try:
            from calendar import timegm
            return datetime.fromtimestamp(timegm(ts), tz=timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None


def _parse_reuters(raw_text: str) -> list[RawNewsItem]:
    """Parse Reuters Business & Finance RSS feed."""
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
                url=url, source="Reuters", published_at=published, tags=tags[:3],
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


def _parse_x_deltaone(raw_text: str) -> list[RawNewsItem]:
    """Parse X/@DeItaone (Walter Bloomberg) via RSSHub feed."""
    feed = feedparser.parse(raw_text)
    items: list[RawNewsItem] = []
    for entry in feed.entries:
        raw_title = entry.get("title", "").strip()
        content = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        url = entry.get("link", "")
        published = _parse_rss_time(entry)

        title = raw_title or (content[:80] + "..." if len(content) > 80 else content)
        if title and url:
            items.append(RawNewsItem(
                title=title, content=content or title,
                url=url, source="X/Walter Bloomberg", published_at=published,
                tags=["WalterBloomberg"],
            ))
    return items


# ════════════════════════════════════════════════════════
# Feed Source Registry
# ════════════════════════════════════════════════════════

@dataclass
class FeedSource:
    name: str
    url: str
    parser: Callable
    is_rss: bool = False  # True = fetch raw text and parse with feedparser


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
    FeedSource(
        name="同花顺",
        url="https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=30",
        parser=_parse_10jqka,
    ),
    FeedSource(
        name="东方财富公告",
        url="https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=20&page_index=1&ann_type=A&client_source=web&f_node=0",
        parser=_parse_eastmoney_ann,
    ),
    FeedSource(
        name="东方财富快讯",
        url="https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_news_col&column=350&order=1&needInteractData=0&page_index=1&page_size=20&req_trace=a",
        parser=_parse_eastmoney_kuaixun,
    ),
    FeedSource(
        name="第一财经",
        url="https://www.yicai.com/api/ajax/getlatest?page=1&pagesize=20",
        parser=_parse_yicai,
    ),
    # ── International Sources (RSS/Atom XML) ──
    FeedSource(
        name="Reuters",
        url="https://cdn.feedcontrol.net/8/1114-wioSIX3uu8MEj.xml",
        parser=_parse_reuters,
        is_rss=True,
    ),
    FeedSource(
        name="CNBC World",
        url="https://www.cnbc.com/id/100727362/device/rss/rss.html",
        parser=_parse_cnbc,
        is_rss=True,
    ),
    FeedSource(
        name="CNBC US Markets",
        url="https://www.cnbc.com/id/10001147/device/rss/rss.html",
        parser=_parse_cnbc,
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
        name="X/Walter Bloomberg",
        url="https://rsshub.app/twitter/user/DeItaone",
        parser=_parse_x_deltaone,
        is_rss=True,
    ),
]

# RSSHub 备用实例列表（当主实例不可用时自动切换）
_RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub.pseudoyu.com",
]


# ════════════════════════════════════════════════════════
# Core Fetch Logic
# ════════════════════════════════════════════════════════

async def _fetch_single_source(
    client: httpx.AsyncClient,
    source: FeedSource,
    r: aioredis.Redis,
) -> list[RawNewsItem]:
    """Fetch and parse one source, dedup against Redis."""
    items: list[RawNewsItem] = []

    # X/Walter Bloomberg: try multiple RSSHub instances as fallback
    if source.name == "X/Walter Bloomberg":
        resp_text = None
        route = "/twitter/user/DeItaone"
        for instance in _RSSHUB_INSTANCES:
            try:
                url = f"{instance}{route}"
                resp = await client.get(url, timeout=20.0)
                resp.raise_for_status()
                resp_text = resp.text
                logger.info("X/Walter Bloomberg fetched via %s", instance)
                break
            except Exception as e:
                logger.warning("RSSHub instance %s failed: %s", instance, e)
                continue
        if resp_text is None:
            logger.warning("All RSSHub instances failed for X/Walter Bloomberg")
            return items
        try:
            raw_items = source.parser(resp_text)
        except Exception as e:
            logger.error("Parser error for %s: %s", source.name, e)
            return items
    else:
        try:
            resp = await client.get(source.url, timeout=20.0)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", source.name, e)
            return items

        try:
            if source.is_rss:
                raw_items = source.parser(resp.text)
            else:
                raw_items = source.parser(resp.json())
        except Exception as e:
            logger.error("Parser error for %s: %s", source.name, e)
            return items

    logger.info("Parsed %d raw items from %s", len(raw_items), source.name)

    for item in raw_items:
        if not item.url:
            continue

        url_hash = _hash_url(item.url)

        # Redis SADD: 1 = new, 0 = already seen
        is_new = await r.sadd(REDIS_DEDUP_KEY, url_hash)
        if not is_new:
            continue

        if not _should_keep(item.title, item.source):
            logger.debug("Dropped by regex: %s", item.title)
            continue

        items.append(item)

    logger.info("After dedup+filter: %d new items from %s", len(items), source.name)
    return items


async def fetch_all_feeds() -> list[RawNewsItem]:
    """Fetch all configured sources concurrently. Returns deduplicated items."""
    r = get_redis()

    async with httpx.AsyncClient(
        headers=HTTP_HEADERS,
        follow_redirects=True,
    ) as client:
        tasks = [
            _fetch_single_source(client, source, r)
            for source in FEED_SOURCES
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
