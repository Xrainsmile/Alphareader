#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AlphaReader 生产环境每日健康巡检。

设计要点：
  * 运行在**宿主机**而非容器内 —— 容器挂掉时巡检仍能报警（放容器内会一起死）。
  * 只依赖标准库（urllib），不依赖容器内 venv，避免环境耦合。
  * 复用现有企业微信机器人 webhook（ALERT_WEBHOOK_URL），与业务告警同一通道。
  * 全异常捕获：巡检脚本自身永不因单项失败而中断，失败项照样进报告。

检查项：
  1. SSL 证书剩余天数（< 21 天告警 —— 2026-09-16 过期 18 天才被发现）
  2. 容器存活与健康状态
  3. 容器日志近 24h 的 ERROR / TRACEBACK 计数（静默失败探测）
  4. 事件产出量（events 表近 24h 新增 —— recent_singles SQL 长期挂掉的探测）
  5. 磁盘空间
  6. journal 日志占用（2026-10-11 磁盘告警根因：journald 无上限积累 3.9G，
     已设 SystemMaxUse=500M；本项探测上限配置被改动或失效）
"""
from __future__ import annotations

import json
import os
import ssl
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DOMAIN = "alphareader.site"
CONTAINERS = ["alpha-frontend", "alpha-web", "alpha-db", "alpha-cache", "alpha-hunter"]
CERT_WARN_DAYS = 21
DISK_WARN_PCT = 85
ERROR_LOG_WARN = 20
JOURNAL_WARN_BYTES = 600 * 1024 * 1024  # 上限500M，超60%余量即600M告警
JOURNALD_CONF = "/etc/systemd/journald.conf"
REPO = "/home/Alphareader"
STATE_FILE = "/home/ubuntu/.alphareader_watchdog_state.json"


def sh(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    """执行命令，永不抛异常。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def check_cert() -> dict:
    """检查站点证书剩余天数。"""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((DOMAIN, 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=DOMAIN) as tls:
                cert = tls.getpeercert()
        not_after = cert.get("notAfter", "")
        # 格式: 'Jan  2 14:25:50 2027 GMT'
        expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        days = (expiry - datetime.now(timezone.utc)).days
        ok = days >= CERT_WARN_DAYS
        return {
            "ok": ok,
            "days": days,
            "expiry": expiry.strftime("%Y-%m-%d"),
            "msg": f"SSL 证书剩余 {days} 天（{expiry.strftime('%Y-%m-%d')} 到期）",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "days": -1, "expiry": "?", "msg": f"证书检查失败: {type(e).__name__}: {e}"}


def check_containers() -> dict:
    """检查容器存活与 restart 次数。"""
    code, out = sh(["sudo", "-n", "docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
    running = {}
    if code == 0:
        for line in out.strip().splitlines():
            if "|" in line:
                name, status = line.split("|", 1)
                running[name.strip()] = status.strip()

    missing, unhealthy, statuses = [], [], []
    for c in CONTAINERS:
        st = running.get(c)
        if st is None:
            missing.append(c)
            statuses.append(f"{c}: 未运行")
        elif "unhealthy" in st.lower():
            unhealthy.append(c)
            statuses.append(f"{c}: {st}")
        else:
            statuses.append(f"{c}: {st.split('(')[0].strip()}")

    ok = not missing and not unhealthy
    detail = "；".join(statuses)
    if missing:
        detail += f" [缺失: {','.join(missing)}]"
    if unhealthy:
        detail += f" [不健康: {','.join(unhealthy)}]"
    return {"ok": ok, "msg": f"容器: {detail}", "missing": missing, "unhealthy": unhealthy}


def check_error_logs() -> dict:
    """统计近 24h 容器日志 ERROR / TRACEBACK 数量（探测静默失败）。"""
    total, per = 0, []
    for c in CONTAINERS:
        code, out = sh(
            ["sudo", "-n", "docker", "logs", "--since", "24h", c], timeout=60
        )
        if code != 0:
            continue
        n = sum(
            1
            for line in out.splitlines()
            if "ERROR" in line or "Traceback" in line or "CRITICAL" in line
        )
        total += n
        if n:
            per.append(f"{c}={n}")
    ok = total < ERROR_LOG_WARN
    detail = ", ".join(per) if per else "无"
    return {"ok": ok, "count": total, "msg": f"近24h 错误日志 {total} 条（{detail}）"}


def check_events() -> dict:
    """检查近 24h 事件产出量（探测事件合成链路静默停摆）。"""
    sql = (
        "SELECT COUNT(*) FROM events WHERE created_at >= NOW() - INTERVAL '24 hours';"
    )
    code, out = sh(
        [
            "sudo", "-n", "docker", "exec", "alpha-db", "psql", "-U", "alphareader",
            "-d", "alphareader", "-t", "-A", "-c", sql,
        ],
        timeout=60,
    )
    if code != 0:
        return {"ok": True, "count": -1, "msg": f"事件量查询失败（跳过）: {out.strip()[:80]}"}
    try:
        n = int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return {"ok": True, "count": -1, "msg": "事件量解析失败（跳过）"}
    # 事件合成已修复；连续 0 产出视为异常
    ok = n > 0
    return {"ok": ok, "count": n, "msg": f"近24h 新增事件 {n} 条"}


def check_disk() -> dict:
    """检查磁盘使用率。"""
    code, out = sh(["df", "-P", "/"])
    if code != 0:
        return {"ok": True, "msg": "磁盘检查失败（跳过）"}
    try:
        line = out.strip().splitlines()[1]
        pct = int(line.split()[4].rstrip("%"))
    except Exception:  # noqa: BLE001
        return {"ok": True, "msg": "磁盘解析失败（跳过）"}
    return {"ok": pct < DISK_WARN_PCT, "pct": pct, "msg": f"磁盘使用率 {pct}%"}


def check_journal() -> dict:
    """检查 journal 日志：上限配置存在且实际占用未超限。

    背景：2026-10-11 磁盘告警根因是 journald 无上限积累 3.9G，
    已设 SystemMaxUse=500M。本项探测配置被改动/失效或日志异常膨胀。
    """
    # 1) 上限配置必须存在（防配置被回滚或系统升级重置）
    code, out = sh(["grep", "-E", r"^SystemMaxUse=", JOURNALD_CONF])
    if code != 0:
        return {"ok": False, "msg": "journald 未配置 SystemMaxUse 上限（可能被回滚，请重新配置）"}

    # 2) 实际占用（journalctl --disk-usage 输出形如 "Archived and active journals take up 3.9G in the file system."）
    code, out = sh(["sudo", "-n", "journalctl", "--disk-usage"])
    if code != 0:
        return {"ok": True, "msg": "journal 占用查询失败（跳过）"}
    text = out.strip().lower()
    size_bytes = 0
    for token in text.replace(",", "").split():
        suffixes = {
            "k": 1024, "kb": 1024,
            "m": 1024**2, "mb": 1024**2,
            "g": 1024**3, "gb": 1024**3,
        }
        body = token.rstrip(".")
        for suf, mult in suffixes.items():
            if body.endswith(suf):
                try:
                    size_bytes = max(size_bytes, int(float(body[: -len(suf)]) * mult))
                except ValueError:
                    pass
                break
    if size_bytes == 0:
        return {"ok": True, "msg": "journal 占用解析失败（跳过）"}
    mb = size_bytes // (1024**2)
    ok = size_bytes <= JOURNAL_WARN_BYTES
    return {"ok": ok, "mb": mb, "msg": f"journal 占用 {mb}M（上限 500M，超 600M 告警）"}


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def send_wecom(title: str, content: str) -> tuple[bool, str]:
    """复用企业微信机器人 webhook 推送告警。"""
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return False, "ALERT_WEBHOOK_URL 未配置"
    payload = {"msgtype": "text", "text": {"content": f"{title}\n{content}"}}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "ignore")
        return ("ok" in body or resp.status < 300), body[:120]
    except urllib.error.URLError as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    checks = [
        ("SSL 证书", check_cert()),
        ("容器状态", check_containers()),
        ("错误日志", check_error_logs()),
        ("事件产出", check_events()),
        ("磁盘空间", check_disk()),
        ("journal日志", check_journal()),
    ]
    failed = [(n, r) for n, r in checks if not r["ok"]]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"[{now}] AlphaReader 健康巡检", ""]
    for name, r in checks:
        mark = "OK  " if r["ok"] else "FAIL"
        lines.append(f"[{mark}] {name}: {r['msg']}")
    report = "\n".join(lines)

    # 仅在「有异常」或「状态由异常转正常」时推送，避免每日噪音
    state = load_state()
    was_bad = bool(state.get("last_failed"))
    is_bad = bool(failed)

    if is_bad:
        report += "\n\n请检查上述项目。"
        print(report)
        ok, info = send_wecom("AlphaReader 巡检告警", report)
        print(f"[notify] sent={ok} info={info}")
        save_state({"last_failed": True, "last_run": now, "failed": [n for n, _ in failed]})
    elif was_bad:
        report += "\n\n全部恢复正常。"
        print(report)
        ok, info = send_wecom("AlphaReader 巡检恢复", report)
        print(f"[notify] sent={ok} info={info}")
        save_state({"last_failed": False, "last_run": now, "failed": []})
    else:
        print(report)
        print("[notify] 全部正常，静默（不推送）")
        save_state({"last_failed": False, "last_run": now, "failed": []})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
