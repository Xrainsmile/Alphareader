"""VCP 检测算法纯逻辑测试（无需数据库）。

验证：
  - 标准 VCP（振幅递减 + 量能递减 + 逼近枢轴）识别为 True
  - 强上升趋势被拒
  - 等幅震荡被拒
  - 数据不足被拒
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vcp_detector import detect_vcp


def _bars(closes, vols=None):
    if vols is None:
        vols = [1e6] * len(closes)
    return [{
        "date": f"2024-01-{i+1:02d}", "open": c, "high": c, "low": c,
        "close": c, "volume": vols[i],
    } for i, c in enumerate(closes)]


def _build_vcp():
    closes = [50 + 50 * i / 24 for i in range(25)]  # 爬升 50→100（枢轴）
    closes += [88, 95, 92, 97, 94, 99, 99]          # 3 次收缩 + 末价近枢轴
    while len(closes) < 45:
        closes.append(99)
    vols = [1e6] * 25 + [9e5, 6e5, 5e5, 3e5, 2e5, 1e5, 1e5] + [1e5] * (len(closes) - 32)
    return _bars(closes, vols)


def test_vcp_detected():
    r = detect_vcp(_build_vcp())
    assert r["vcp_detected"] is True, r["reason"]
    assert r["contractions"] == 3
    assert r["decay_ok"] is True
    assert r["vol_decay_ok"] is True
    assert r["near_pivot"] is True
    assert r["pivot_suggested"] == 100.0


def test_uptrend_rejected():
    up = [50 + 2 * i for i in range(60)]
    r = detect_vcp(_bars(up))
    assert r["vcp_detected"] is False
    assert "收缩次数" in r["reason"]


def test_flat_rejected():
    flat = [100 if i % 2 == 0 else 90 for i in range(60)]
    r = detect_vcp(_bars(flat))
    assert r["vcp_detected"] is False


def test_insufficient_data():
    r = detect_vcp(_bars([100, 90, 95]))
    assert r["vcp_detected"] is False
    assert "数据不足" in r["reason"]


def test_pivot_override():
    r = detect_vcp(_build_vcp(), pivot_override=99.0)
    assert r["pivot_price"] == 99.0
    assert r["near_pivot"] is True
