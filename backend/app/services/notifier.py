"""Webhook 告警通知器 — Pipeline 失败/跳过时发送告警消息。

支持的平台（根据 URL 自动识别）：
  - 飞书（Feishu / Lark）：feishu.cn / larksuite.com
  - 钉钉（DingTalk）：dingtalk.com / oapi.dingtalk
  - 企业微信（WeCom）：qyapi.weixin.qq.com
  - Slack：hooks.slack.com
  - 通用 Webhook（Generic JSON POST）

配置方式：
  环境变量 ALERT_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  留空则禁用告警（默认禁用）。

设计原则：
  send_alert() 永远不抛异常 — 告警失败只记录日志，不影响主 Pipeline 流程。
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger("alphareader.notifier")

# ── Webhook 请求超时配置（秒）──
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)  # 总超时10秒，连接超时5秒


def _detect_platform(url: str) -> str:
    """根据 Webhook URL 自动识别平台类型。"""
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
    """根据平台类型构建对应格式的 JSON 请求体。

    各平台消息格式不同：
      - 飞书：{"msg_type": "text", "content": {"text": ...}}
      - 钉钉：{"msgtype": "text", "text": {"content": ...}}
      - 企微：{"msgtype": "text", "text": {"content": ...}}
      - Slack：{"text": ...}
      - 通用：{"title": ..., "message": ..., "timestamp": ..., "app": ...}
    """
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
    """通过配置的 Webhook 发送告警消息。URL 为空时静默跳过。

    此函数永远不抛异常 — 发送失败仅记录 warning 日志，
    确保告警模块的故障不会影响主 Pipeline 的正常运行。
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
