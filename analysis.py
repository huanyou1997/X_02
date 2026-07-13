# -*- coding: utf-8 -*-
"""analysis.py — 指标与支撑/压力引擎

从你的 PWA (btc-perp-signal-pwa/src/lib) 逐行移植, 保持完全相同的口径:
  · ema_series / rsi / atr        ← indicators.js  (SMA 播种 EMA, Wilder RSI/ATR)
  · fractal_pivots / volume_profile / compute_sr
                                   ← srlevels.js    (支撑/压力 v2: 三源共振 + 触碰验证
                                                     + ATR 自适应聚类 + 强度评分 0-100)
  · detect_walls / analyze_order_flow
                                   ← orderflow.js   ($100万 鲸鱼墙, 0.05% 网格聚簇,
                                                     ±0.5% 近端失衡)
这样机器人报出来的位和 PWA 面板显示的位是同一套数字。
"""
from __future__ import annotations

import math
import time
from statistics import median as _median


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def median(a):
    return float(_median(a)) if a else 0.0


def mean(a):
    return sum(a) / len(a) if a else 0.0


# ---------------------------------------------------------------- 基础指标 --
def ema_series(values, period):
    """完整 EMA 序列 (SMA 播种), 与 indicators.js emaSeries 一致"""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [None] * len(values)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def ema(values, period):
    s = ema_series(values, period)
    return s[-1] if s else None


def rsi(closes, period=14):
    """Wilder RSI, 返回最新值"""
    n = len(closes)
    if n < period + 1:
        return None
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gain += d
        else:
            loss -= d
    ag, al = gain / period, loss / period
    val = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        val = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return val


def atr(highs, lows, closes, period=14):
    """Wilder ATR"""
    n = len(closes)
    if n < period + 1:
        return None
    tr = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, n)
    ]
    a = sum(tr[:period]) / period
    for i in range(period, len(tr)):
        a = (a * (period - 1) + tr[i]) / period
    return a


# ------------------------------------------------------------- 分形枢轴 --
def fractal_pivots(h, l, k=2):
    """左右各 k 根更极端才算枢轴 (与 srlevels.js fractalPivots 一致)"""
    ph, pl = [], []
    for i in range(k, len(h) - k):
        is_h = all(h[j] < h[i] for j in range(i - k, i + k + 1) if j != i)
        is_l = all(l[j] > l[i] for j in range(i - k, i + k + 1) if j != i)
        if is_h:
            ph.append({"i": i, "price": h[i]})
        if is_l:
            pl.append({"i": i, "price": l[i]})
    return ph, pl


# --------------------------------------------------------- 成交量分布 HVN --
def volume_profile(candles, mid, atr_v):
    """把每根K线的量摊到其覆盖的价格桶, 取局部峰值 = 高成交密集区"""
    bucket = max(atr_v * 0.2, mid * 0.0006)
    vol = {}
    for c in candles:
        lo, hi = min(c["l"], c["h"]), max(c["l"], c["h"])
        b0, b1 = int(lo // bucket), int(hi // bucket)
        span = max(1, b1 - b0 + 1)
        per = (c.get("v") or 0) / span
        for b in range(b0, b1 + 1):
            vol[b] = vol.get(b, 0.0) + per
    entries = sorted(vol.items())
    vals = [v for _, v in entries if v > 0]
    med = median(vals)
    hvns = []
    for i, (b, v) in enumerate(entries):
        if v < med * 1.5:
            continue
        lo_i, hi_i = max(0, i - 2), min(len(entries) - 1, i + 2)
        if any(entries[j][1] > v for j in range(lo_i, hi_i + 1) if j != i):
            continue
        hvns.append({"price": (b + 0.5) * bucket, "v": v})
    hvns.sort(key=lambda x: -x["v"])
    return hvns[:12]


# ------------------------------------------------- 支撑/压力 v2 (computeSR) --
def compute_sr(candles, mid, atr_v, walls=None):
    """三源候选共振 (枢轴 × HVN × 挂单墙) + 触碰验证 + 强度评分。
    输出严格最近在前: 压力 R1<R2<R3, 支撑 S1>S2>S3。"""
    walls = walls or []
    n = len(candles)
    empty = {"support": [], "resistance": []}
    if n < 20 or not mid:
        return empty
    h = [c["h"] for c in candles]
    l = [c["l"] for c in candles]
    cc = [c["c"] for c in candles]
    tol_c = max(atr_v * 0.35, mid * 0.0012)   # 聚类容差
    tol_t = max(atr_v * 0.22, mid * 0.0008)   # 触碰容差
    min_dist = atr_v * 0.35                   # 距现价噪声带

    # --- 候选 ---
    cands = []
    ph, pl = fractal_pivots(h, l, 2)
    for p in ph:
        cands.append({"price": p["price"], "w": 1 + 0.8 * (p["i"] / n), "pivot": 1})
    for p in pl:
        cands.append({"price": p["price"], "w": 1 + 0.8 * (p["i"] / n), "pivot": 1})
    for v in volume_profile(candles, mid, atr_v):
        cands.append({"price": v["price"], "w": 1.5, "hvn": 1})
    for w in walls:
        p = (w or {}).get("price")
        if p is not None and math.isfinite(p):
            cands.append({
                "price": float(p),
                "w": 1.6 + clamp((w.get("notional") or 0) / 1e7, 0, 1) * 0.8,
                "wall": 1, "wallStr": w.get("notionalStr"),
            })
    if not cands:
        return empty

    # --- 聚类 ---
    cands.sort(key=lambda x: x["price"])
    clusters = []
    for x in cands:
        g = clusters[-1] if clusters else None
        if g is not None and x["price"] - g["pMax"] <= tol_c:
            g["pw"] += x["price"] * x["w"]
            g["wsum"] += x["w"]
            g["pMax"] = x["price"]
            g["pivot"] += x.get("pivot", 0)
            g["hvn"] = g["hvn"] or bool(x.get("hvn"))
            g["wall"] = g["wall"] or bool(x.get("wall"))
            if x.get("wallStr"):
                g["wallStr"] = x["wallStr"]
        else:
            clusters.append({
                "pw": x["price"] * x["w"], "wsum": x["w"], "pMax": x["price"],
                "pivot": x.get("pivot", 0), "hvn": bool(x.get("hvn")),
                "wall": bool(x.get("wall")), "wallStr": x.get("wallStr"),
            })

    # --- 触碰验证 + 强度 ---
    levels = []
    for g in clusters:
        price = g["pw"] / g["wsum"]
        sup_t = res_t = last_touch = 0
        for i in range(n):
            if abs(l[i] - price) <= tol_t and cc[i] > price:
                sup_t += 1
                last_touch = i
            if abs(h[i] - price) <= tol_t and cc[i] < price:
                res_t += 1
                last_touch = i
        recency = last_touch / n

        def mk(side_t, flip_t, g=g, recency=recency):
            return round(clamp(
                min(60, side_t * 16 + flip_t * 6)
                + (16 if g["hvn"] else 0) + (18 if g["wall"] else 0)
                + min(12, g["pivot"] * 4) + recency * 8,
                5, 100))

        levels.append({
            "price": round(price), "hvn": g["hvn"], "wall": g["wall"],
            "wallStr": g.get("wallStr"),
            "supTouch": sup_t, "resTouch": res_t,
            "strengthAsSup": mk(sup_t, res_t), "strengthAsRes": mk(res_t, sup_t),
        })

    # --- 分侧, 最近在前, 优先强位 (≥22) ---
    def pick(is_sup):
        side = [
            {
                "price": x["price"],
                "strength": x["strengthAsSup"] if is_sup else x["strengthAsRes"],
                "touches": x["supTouch"] if is_sup else x["resTouch"],
                "hvn": x["hvn"], "wall": x["wall"], "wallStr": x["wallStr"],
            }
            for x in levels
            if (x["price"] <= mid - min_dist if is_sup else x["price"] >= mid + min_dist)
        ]
        side.sort(key=lambda a: (mid - a["price"]) if is_sup else (a["price"] - mid))
        out = [x for x in side if x["strength"] >= 22][:3]
        for x in side:
            if len(out) >= 3:
                break
            if x not in out:
                out.append(x)
        out.sort(key=lambda a: (mid - a["price"]) if is_sup else (a["price"] - mid))
        return out

    resistance, support = pick(False), pick(True)

    # --- 兜底补齐 (稀疏数据): ATR 外推 ---
    recent_high = max(h[-30:])
    recent_low = min(l[-30:])
    while len(resistance) < 3:
        base = resistance[-1]["price"] if resistance else max(recent_high, mid + min_dist)
        resistance.append({"price": round(base + atr_v), "strength": 10, "touches": 0,
                           "hvn": False, "wall": False, "wallStr": None})
    while len(support) < 3:
        base = support[-1]["price"] if support else min(recent_low, mid - min_dist)
        support.append({"price": round(base - atr_v), "strength": 10, "touches": 0,
                        "hvn": False, "wall": False, "wallStr": None})
    return {"support": support, "resistance": resistance}


# ------------------------------------------------- 订单流 · 超大额挂单墙 --
def fmt_notional(v):
    return f"${v / 1e8:.2f}亿" if v >= 1e8 else f"${round(v / 1e4)}万"


def detect_walls(levels, side, mid, min_abs=1_000_000):
    """稳健离群检测: 阈值 = max(中位数×6, μ+2.5σ, $100万); 0.05% 网格聚簇"""
    rng = max(5000, mid * 0.08)
    rows = [{"p": p, "n": p * q} for p, q in levels
            if math.isfinite(p * q) and p * q > 0 and abs(p - mid) <= rng]
    if len(rows) < 10:
        return {"walls": [], "total": 0}
    total = sum(r["n"] for r in rows)
    ns = [r["n"] for r in rows]
    med, mu = median(ns), mean(ns)
    sd = math.sqrt(mean([(x - mu) ** 2 for x in ns]))
    thr = max(med * 6, mu + 2.5 * sd, min_abs)
    tol = mid * 0.0005
    big = sorted([r for r in rows if r["n"] >= thr * 0.55], key=lambda r: r["p"])
    clusters = []
    for r in big:
        c = clusters[-1] if clusters else None
        if c is not None and r["p"] - c["pMax"] <= tol:
            c["n"] += r["n"]
            c["pw"] += r["p"] * r["n"]
            c["pMax"] = r["p"]
            c["cnt"] += 1
        else:
            clusters.append({"n": r["n"], "pw": r["p"] * r["n"], "pMax": r["p"], "cnt": 1})
    walls = [
        {"side": side, "price": round(c["pw"] / c["n"]), "notional": c["n"],
         "notionalStr": fmt_notional(c["n"]), "levels": c["cnt"],
         "sharePct": round(c["n"] / total * 100, 1)}
        for c in clusters if c["n"] >= thr
    ]
    return {"walls": walls, "total": total}


def analyze_order_flow(book, mid, atr_v):
    if (not book or len(book.get("bids", [])) < 10
            or len(book.get("asks", [])) < 10 or not mid):
        return None
    bid_r = detect_walls(book["bids"], "bid", mid)
    ask_r = detect_walls(book["asks"], "ask", mid)
    band = mid * 0.005
    near_bid = sum(p * q for p, q in book["bids"] if p >= mid - band)
    near_ask = sum(p * q for p, q in book["asks"] if p <= mid + band)
    tot = near_bid + near_ask
    bid_share = round(near_bid / tot * 100, 1) if tot > 0 else 50.0
    bias = "买盘偏强" if bid_share >= 57 else "卖盘偏强" if bid_share <= 43 else "均衡"
    below = sorted([w for w in bid_r["walls"] if w["price"] < mid],
                   key=lambda w: mid - w["price"])[:3]
    above = sorted([w for w in ask_r["walls"] if w["price"] > mid],
                   key=lambda w: w["price"] - mid)[:3]
    strongest = max(below + above, key=lambda w: w["notional"], default=None)
    return {"above": above, "below": below, "strongest": strongest,
            "bidSharePct": bid_share, "askSharePct": round(100 - bid_share, 1),
            "bias": bias}


# --------------------------------------------------------- 日报总装 analyze --
def _fix_wall_tags(levels_list, walls):
    """显示层校正: 聚类是链式的, 远处巨墙的金额标注可能被"传染"到簇均价上。
    这里把"巨墙"注记重新挂到与墙价相差 ≤0.6% 的位上, 其余位清除墙注记。
    (只修显示归属, 不改 PWA 口径的强度评分)"""
    for x in levels_list:
        near = [w for w in walls
                if abs(w["price"] - x["price"]) <= x["price"] * 0.006]
        if near:
            w = max(near, key=lambda k: k["notional"])
            x["wall"], x["wallStr"] = True, w["notionalStr"]
        else:
            x["wall"], x["wallStr"] = False, None


def _struct_text(d1):
    """日线市场结构: 高低点抬升 / 下移 / 交错"""
    ph, pl = fractal_pivots([k["h"] for k in d1], [k["l"] for k in d1], 2)
    if len(ph) >= 2 and len(pl) >= 2:
        hh = ph[-1]["price"] > ph[-2]["price"]
        hl = pl[-1]["price"] > pl[-2]["price"]
        if hh and hl:
            return "up", "高低点抬升"
        if not hh and not hl:
            return "down", "高低点下移"
    return "mixed", "高低点交错"


def analyze(bg, bn=None):
    """bg = exchanges.fetch_bitget() 结果, bn = fetch_binance() 结果(可为 None/错误)"""
    tk, d1, h4 = bg["ticker"], bg["d1"], bg["h4"]
    mid = tk["last"]
    h4h = [k["h"] for k in h4]
    h4l = [k["l"] for k in h4]
    h4c = [k["c"] for k in h4]
    d1c = [k["c"] for k in d1]

    atr4 = atr(h4h, h4l, h4c) or mid * 0.01
    atrd = atr([k["h"] for k in d1], [k["l"] for k in d1], d1c) or mid * 0.02

    # 盘口挂单墙 (三源之一; 盘口缺失时自动降级为 枢轴×HVN 双源)
    of = analyze_order_flow(bg.get("book"), mid, atr4)
    walls = (of["below"] + of["above"]) if of else []

    sr4 = compute_sr(h4[-200:], mid, atr4, walls)       # 当日操作级 (≈33天 4H)
    srd = compute_sr(d1[-150:], mid, atrd, walls)       # 波段级 (≈5个月 日线)
    for side in ("resistance", "support"):
        _fix_wall_tags(sr4[side], walls)
        _fix_wall_tags(srd[side], walls)

    # 日线趋势 & 结构
    e21d, e50d = ema(d1c, 21), ema(d1c, 50)
    day_dir = "range"
    if e21d and e50d:
        if mid > e21d > e50d:
            day_dir = "bull"
        elif mid < e21d < e50d:
            day_dir = "bear"
    _, struct_text = _struct_text(d1)

    # 4H 趋势 / RSI / 箱体
    e21h, e50h = ema(h4c, 21), ema(h4c, 50)
    h4_dir = "range"
    if e21h and e50h:
        if h4c[-1] > e21h > e50h:
            h4_dir = "bull"
        elif h4c[-1] < e21h < e50h:
            h4_dir = "bear"
    rsi4 = rsi(h4c) or 50.0
    win = h4[-42:]                                       # 近 7 天
    r_hi = max(k["h"] for k in win)
    r_lo = min(k["l"] for k in win)
    span_pct = (r_hi - r_lo) / mid * 100
    ranging = span_pct <= 5.0
    touch_top = sum(1 for k in win if k["h"] >= r_hi * (1 - 0.004))
    touch_bot = sum(1 for k in win if k["l"] <= r_lo * (1 + 0.004))

    # 量能: 24h 成交额 vs 最近 7 根完整日K均值
    day_ms = 86400_000
    now_ms = tk.get("ts") or int(time.time() * 1000)
    today0 = (now_ms // day_ms) * day_ms
    complete = [k for k in d1 if k["t"] < today0]
    qv7 = [(k.get("qv") or k["c"] * (k.get("v") or 0)) for k in complete[-7:]]
    v7 = mean([x for x in qv7 if x > 0])
    v24 = tk.get("quote_vol") or 0
    if not v24:
        v24 = sum((k.get("qv") or k["c"] * (k.get("v") or 0)) for k in h4[-6:])
    ratio7 = (v24 / v7 * 100) if v7 else None

    # 涨跌幅 / 基差
    chg24 = None
    if tk.get("open24"):
        chg24 = (mid - tk["open24"]) / tk["open24"] * 100
    basis = None
    if tk.get("index"):
        basis = (mid - tk["index"]) / tk["index"] * 100

    # 币安辅助: 交叉校验 + 主动买盘 + OI 变化
    check = None
    taker = oi_chg = None
    bn_ok = bool(bn) and not bn.get("error")
    if bn_ok:
        diff = (mid - bn["last"]) / bn["last"] * 100
        check = {"ok": abs(diff) <= 0.15, "bg": mid, "bn": bn["last"], "diff": diff}
        taker = bn.get("taker_buy_pct")
        oi_chg = bn.get("oi_chg24_pct")

    return {
        "price": mid,
        "chg24": chg24,
        "atr4": atr4,
        "day": {"dir": day_dir, "ema21": e21d or mid, "ema50": e50d or mid,
                "struct_text": struct_text},
        "day_levels": {"res": srd["resistance"], "sup": srd["support"]},
        "h4": {"dir": h4_dir, "ema21": e21h or mid, "ema50": e50h or mid,
               "rsi": rsi4, "ranging": ranging, "range_hi": r_hi, "range_lo": r_lo,
               "range_days": len(win) * 4 / 24, "span_pct": span_pct,
               "touch_top": touch_top, "touch_bot": touch_bot},
        "levels": {"res": sr4["resistance"], "sup": sr4["support"]},
        "orderflow": of,
        "vol": {"v24": v24, "ratio7": ratio7, "funding": tk.get("funding"),
                "oi": tk.get("oi"), "oi_chg": oi_chg, "taker": taker, "basis": basis},
        "check": check,
        "bn_error": (bn or {}).get("error") if bn else "missing",
    }
