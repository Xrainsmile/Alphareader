"""Webhook notifier — send alerts on pipeline failure / misfire.

Supports generic webhook (JSON POST), with built-in formatting for:
  - 飞书 (Feishu / Lark)
  - 钉钉 (DingTalk)
  - 企业微信 (WeCom)
  - Slack
  - Generic (custom JSON payload)

Configure via environment variable:
  ALERT_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

The notifier auto-detects the platform from the URL and formats the
payload accordingly. Set ALERT_WEBHOOK_URL="" to disable (default).
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger("alphareader.notifier")

# ── Timeout for webhook calls (seconds) ──
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _detect_platform(url: str) -> str:
    """Auto-detect webhook platform from URL."""
    if "feishu.cn" in url or "larksuite.com" in url:
        return "feishu"
    if "dingtalk.com" in url or "oapi.dingtalk" in url:
        return "dingtalk"
    if "qyapi.weixin.qq.com" in url:
        return "wecom"
    if "hooks.slack.com" in url:
        return "slack"
    return "generic"


def _build_payload(platform: str, title: str, message: str) -> dict:
    """Build platform-specific JSON payload."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{ts}] {title}\n{message}"

    if platform == "feishu":
        return {
            "msg_type": "text",
            "content": {"text": full_msg},
        }

    if platform == "dingtalk":
        return {
            "msgtype": "text",
            "text": {"content": full_msg},
        }

    if platform == "wecom":
        return {
            "msgtype": "text",
            "text": {"content": full_msg},
        }

    if platform == "slack":
        return {"text": full_msg}

    # Generic: just send a JSON object
    return {
        "title": title,
        "message": message,
        "timestamp": ts,
        "app": "AlphaReader",
    }


async def send_alert(title: str, message: str) -> None:
    """Send an alert via the configured webhook. No-op if URL is empty.

    This function never raises — failures are logged and swallowed
    so that alerting issues don't break the main pipeline.
    """
    url = settings.ALERT_WEBHOOK_URL
    if not url:
        return  # Alerting disabled

    platform = _detect_platform(url)
    payload = _build_payload(platform, title, message)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code < 300:
                logger.info("Alert sent (%s): %s", platform, title)
            else:
                logger.warning(
                    "Alert webhook returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as e:
        # Never let notification failure crash the caller
        logger.warning("Failed to send alert (%s): %s", platform, e)
