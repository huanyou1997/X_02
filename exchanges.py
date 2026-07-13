# -*- coding: utf-8 -*-
"""exchanges.py — 行情数据源

主数据源 = Bitget v2 合约公开行情 (与 PWA 同一组接口):
    /api/v2/mix/market/ticker          现价/24h量/持仓/费率/指数价
    /api/v2/mix/market/candles         日K(1Dutc, 兜底1D) + 4H, UTC 对齐
    /api/v2/mix/market/merge-depth     深度级联 1000 → orderbook 200 → merge-depth 50
辅助验证 = 币安 U 本位合约公开行情:
    /fapi/v1/ticker/24hr               价格交叉校验 + 24h 成交额
    /fapi/v1/premiumIndex              标记价/指数价/资金费率
    /fapi/v1/klines (4h)               主动买盘占比 (taker buy)
    /futures/data/openInterestHist     持仓量 24h 变化
币安整体是"锦上添花": 任何失败(含美区 IP 451)都不会中断报告,
只是降级为 Bitget 单源, 并在推文里如实标注。
"""
from __future__ import annotations

import time

import requests

BITGET = "https://api.bitget.com"
BINANCE_FAPI = "https://fapi.binance.com"
HEADERS = {"User-Agent": "btc-daily-report-bot/1.0", "Accept": "application/json"}


class BlockedError(Exception):
    """HTTP 451 — 请求方 IP 所在地区被交易所限制"""


def _get(url, params=None, timeout=15, retries=3, backoff=2.0):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 451:
                raise BlockedError(f"HTTP 451 地区受限: {url}")
            r.raise_for_status()
            return r.json()
        except BlockedError:
            raise
        except Exception as e:  # noqa: BLE001 — 重试后如仍失败, 原样抛出
            last = e
            time.sleep(backoff * (i + 1))
    raise last


# ------------------------------------------------------------------ Bitget --
def _bg_get(path, params):
    j = _get(BITGET + path, params)
    code = str(j.get("code", "00000"))
    if code not in ("00000", "0"):
        raise RuntimeError(f"Bitget 接口错误 {code} {j.get('msg', '')}")
    return j.get("data")


def _norm_candles(rows):
    out = []
    for r in rows or []:
        try:
            k = {"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]),
                 "v": float(r[5]) if len(r) > 5 else 0.0,
                 "qv": float(r[6]) if len(r) > 6 else 0.0}
        except (ValueError, IndexError, TypeError):
            continue
        if all(map(lambda x: x == x, (k["o"], k["c"]))):  # 过滤 NaN
            out.append(k)
    out.sort(key=lambda k: k["t"])
    return out


def _bg_candles(q, gran_list, limit):
    last = None
    for g in gran_list:
        try:
            rows = _bg_get("/api/v2/mix/market/candles",
                           {**q, "granularity": g, "limit": str(limit)})
            ks = _norm_candles(rows)
            if ks:
                return ks
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"Bitget K线获取失败({'/'.join(gran_list)}): {last}")


def fetch_bitget(symbol="BTCUSDT"):
    q = {"symbol": symbol, "productType": "USDT-FUTURES"}

    # --- ticker (核心, 失败即抛错) ---
    d0 = _bg_get("/api/v2/mix/market/ticker", q)
    d = d0[0] if isinstance(d0, list) else d0
    fnum = lambda key: float(d[key]) if d.get(key) not in (None, "") else 0.0  # noqa: E731
    ticker = {
        "last": fnum("lastPr"),
        "open24": fnum("open24h"),
        "high24": fnum("high24h"),
        "low24": fnum("low24h"),
        "base_vol": fnum("baseVolume"),
        "quote_vol": fnum("usdtVolume") or fnum("quoteVolume"),
        "oi": fnum("holdingAmount"),
        "funding": float(d["fundingRate"]) if d.get("fundingRate") not in (None, "") else None,
        "index": fnum("indexPrice") or None,
        "ts": int(d.get("ts") or time.time() * 1000),
    }
    if not ticker["last"]:
        raise RuntimeError("Bitget ticker 无 lastPr")

    # --- K线 (核心): 日K 用 UTC 对齐(与币安同口径), 兜底普通 1D ---
    d1 = _bg_candles(q, ["1Dutc", "1D"], 150)
    h4 = _bg_candles(q, ["4H"], 200)

    # --- 深度级联 (非核心, 失败降级): merge-depth 1000 → orderbook 200 → merge-depth 50 ---
    book = None
    for path, lim in (("/api/v2/mix/market/merge-depth", 1000),
                      ("/api/v2/mix/market/orderbook", 200),
                      ("/api/v2/mix/market/merge-depth", 50)):
        try:
            bd = _bg_get(path, {**q, "limit": str(lim)})
            bids = sorted([[float(p), float(s)] for p, s in (bd.get("bids") or [])],
                          key=lambda x: -x[0])
            asks = sorted([[float(p), float(s)] for p, s in (bd.get("asks") or [])],
                          key=lambda x: x[0])
            if len(bids) >= 10 and len(asks) >= 10:
                book = {"bids": bids, "asks": asks}
                break
        except Exception:  # noqa: BLE001
            book = None
    return {"ticker": ticker, "d1": d1, "h4": h4, "book": book}


# ----------------------------------------------------------------- Binance --
def fetch_binance(symbol="BTCUSDT"):
    """辅助验证源。任何失败都返回 {"error": ..., "msg": ...} 而不是抛异常。
    注意: 币安对美国等地区 IP 返回 451 (GitHub Actions 默认跑在美国机房会命中),
    此时报告自动降级为 Bitget 单源。"""
    try:
        t24 = _get(BINANCE_FAPI + "/fapi/v1/ticker/24hr",
                   {"symbol": symbol}, retries=2)
        out = {
            "last": float(t24["lastPrice"]),
            "quote_vol": float(t24.get("quoteVolume") or 0),
        }
        try:
            prem = _get(BINANCE_FAPI + "/fapi/v1/premiumIndex",
                        {"symbol": symbol}, retries=1)
            out["funding"] = (float(prem["lastFundingRate"])
                              if prem.get("lastFundingRate") not in (None, "") else None)
            out["mark"] = float(prem.get("markPrice") or 0) or None
            out["index"] = float(prem.get("indexPrice") or 0) or None
        except Exception:  # noqa: BLE001
            pass
        try:
            kl = _get(BINANCE_FAPI + "/fapi/v1/klines",
                      {"symbol": symbol, "interval": "4h", "limit": 8}, retries=1)
            qv = sum(float(r[7]) for r in kl[-6:])
            tb = sum(float(r[10]) for r in kl[-6:])
            out["taker_buy_pct"] = (tb / qv * 100) if qv > 0 else None
        except Exception:  # noqa: BLE001
            out["taker_buy_pct"] = None
        try:
            oh = _get(BINANCE_FAPI + "/futures/data/openInterestHist",
                      {"symbol": symbol, "period": "1h", "limit": 25}, retries=1)
            if oh and len(oh) >= 2:
                oi_now = float(oh[-1]["sumOpenInterest"])
                oi_then = float(oh[0]["sumOpenInterest"])
                out["oi"] = oi_now
                out["oi_chg24_pct"] = ((oi_now - oi_then) / oi_then * 100
                                       if oi_then else None)
        except Exception:  # noqa: BLE001
            pass
        return out
    except BlockedError as e:
        return {"error": "blocked", "msg": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": "failed", "msg": f"{type(e).__name__}: {e}"}
