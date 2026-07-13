# -*- coding: utf-8 -*-
"""mock_data.py — 离线演练数据 (--mock)

固定随机种子, 每次生成完全相同的数据, 形态贴近 2026-07 实际行情:
    前 80 天缓涨 67500→75200 → 40 天回落至 64100 → 近 30 天在
    62800-64800 箱体震荡, 现价 63625。
盘口内埋了 4 面鲸鱼级挂单墙, 用来演练"三源共振"的墙因子:
    卖墙 ≈65100($2000万+) / ≈64620(箱体上沿) ; 买墙 ≈62480 / ≈63180。
仅用于本地演示与单元自测, 与真实行情无关。
"""
from __future__ import annotations

import math
import random
import time

DAY_MS = 86400_000
H4_MS = 4 * 3600 * 1000
LAST = 63625.0


def _targets(n=150):
    """分段目标路径 (对数线性插值) + 箱体段叠加正弦摆动"""
    anchors = [(0, 67500.0), (79, 75200.0), (119, 64100.0), (149, LAST)]
    tg = [0.0] * n
    for (i0, p0), (i1, p1) in zip(anchors, anchors[1:]):
        for i in range(i0, i1 + 1):
            f = (i - i0) / max(1, i1 - i0)
            tg[i] = math.exp(math.log(p0) * (1 - f) + math.log(p1) * f)
    for i in range(120, n):                      # 箱体摆动 ±900
        tg[i] = 63700.0 + 900.0 * math.sin((i - 120) / 9.0) + (LAST - 63700.0) * (i - 120) / 29
    return tg


def _mk_daily(n=150, seed=42):
    rnd = random.Random(seed)
    tg = _targets(n)
    closes, noise = [], 0.0
    for i in range(n):
        noise = 0.82 * noise + rnd.gauss(0, 0.009)
        closes.append(tg[i] * math.exp(noise))
    closes[-1] = LAST                             # 锚定现价

    now_ms = int(time.time() * 1000)
    today0 = (now_ms // DAY_MS) * DAY_MS
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c * (1 - rnd.gauss(0, 0.004))
        hi = max(o, c) * (1 + abs(rnd.gauss(0, 0.005)) + 0.001)
        lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.005)) - 0.001)
        ret = abs(c / o - 1) if o else 0.0
        v = 165000.0 * math.exp(rnd.gauss(0, 0.22)) * (1 + min(2.0, ret / 0.02))
        t = today0 - (n - 1 - i) * DAY_MS
        out.append({"t": t, "o": o, "h": hi, "l": lo, "c": c, "v": v,
                    "qv": v * (o + hi + lo + c) / 4})
    return out


def _mk_h4(daily, seed=43, want=200):
    """把最近 34 天日K确定性细分为 6 根 4H:
    收盘沿 o→c 线性推进 + 幅度受控的噪声 (布朗桥式), 保证触及日内高低点。"""
    rnd = random.Random(seed)
    days = daily[-(want // 6 + 1):]
    bars = []
    for d in days:
        o, c, hi_d, lo_d = d["o"], d["c"], d["h"], d["l"]
        rng = max(hi_d - lo_d, o * 0.002)
        pts = [o]
        for k in range(1, 6):
            base = o + (c - o) * k / 6
            pts.append(min(hi_d * 0.9995,
                           max(lo_d * 1.0005, base + rnd.gauss(0, rng * 0.22))))
        pts.append(c)
        pts[rnd.randint(1, 5)] = hi_d * 0.9995      # 保证日内高低点被触及
        pts[rnd.randint(1, 5)] = lo_d * 1.0005
        for k in range(6):
            bo, bc = pts[k], pts[k + 1]
            b_hi = max(bo, bc) * (1 + abs(rnd.gauss(0, 0.0012)))
            b_lo = min(bo, bc) * (1 - abs(rnd.gauss(0, 0.0012)))
            v = d["v"] / 6 * math.exp(rnd.gauss(0, 0.3))
            bars.append({"t": d["t"] + k * H4_MS, "o": bo, "h": b_hi, "l": b_lo,
                         "c": bc, "v": v, "qv": v * (bo + bc) / 2})
    bars = bars[-want:]
    bars[-1]["c"] = LAST
    bars[-1]["h"] = max(bars[-1]["h"], LAST)
    bars[-1]["l"] = min(bars[-1]["l"], LAST)
    return bars


def _mk_book(mid, seed=7):
    rnd = random.Random(seed)
    step = mid * 0.0002
    bids, asks = [], []
    for i in range(1, 401):                        # 双侧各 ~8% 深度
        asks.append([mid + i * step, math.exp(rnd.gauss(-0.5, 0.9))])
        bids.append([mid - i * step, math.exp(rnd.gauss(-0.5, 0.9))])

    def add_wall(side, price, total_btc, levels=3):
        idx = min(range(len(side)), key=lambda k: abs(side[k][0] - price))
        for k in range(levels):
            side[min(len(side) - 1, idx + k)][1] += total_btc / levels

    add_wall(asks, mid * 1.0232, 370)              # ≈65100 卖墙 ~$2350万
    add_wall(asks, mid * 1.0156, 95)               # ≈64620 卖墙 (箱体上沿共振)
    add_wall(bids, mid * 0.9820, 235)              # ≈62480 买墙 ~$1470万
    add_wall(bids, mid * 0.9930, 60, levels=2)     # ≈63180 买墙
    return {"bids": bids, "asks": asks}


def load_mock():
    d1 = _mk_daily()
    h4 = _mk_h4(d1)
    last6 = h4[-6:]
    base_vol = sum(k["v"] for k in last6)
    ticker = {
        "last": LAST,
        "open24": last6[0]["o"],
        "high24": max(k["h"] for k in last6),
        "low24": min(k["l"] for k in last6),
        "base_vol": base_vol,
        "quote_vol": sum(k["qv"] for k in last6),
        "oi": 52600.0,
        "funding": 0.000087,
        "index": LAST * 0.99980,
        "ts": int(time.time() * 1000),
    }
    bg = {"ticker": ticker, "d1": d1, "h4": h4, "book": _mk_book(LAST)}
    bn = {
        "last": 63631.0,
        "quote_vol": 1.42e10,
        "funding": 0.000091,
        "mark": 63640.0,
        "index": 63618.0,
        "taker_buy_pct": 52.4,
        "oi": 78450.0,
        "oi_chg24_pct": 1.8,
    }
    return bg, bn
