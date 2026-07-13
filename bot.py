#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot.py — BTCUSDT 永续每日盘面日报 · 手动发布版入口

只生成、不发布: 每次运行产出一份"复制即发"的文案包, 你自己粘贴到 X。
不需要 X 开发者账号、不需要充值、不需要任何密钥。

用法:
    python bot.py                  抓取真实行情, 生成文案 (打印 + 存 last_report.txt)
    python bot.py --mock           内置模拟数据离线演练 (文案会带"请勿发布"水印)
    python bot.py --compact        单条速报模式 (也可用环境变量 COMPACT=1)

环境变量:
    SYMBOL=BTCUSDT   TZ_OFFSET=8   COMPACT=0
    REPORT_FILE=last_report.txt    文案包落盘路径
    ARCHIVE_DIR=                   设为 reports 时额外写 latest.txt + 按日期存档
                                   (GitHub Actions 用它把日报提交进仓库)
    WRITE_ISSUE=0                  1 = 额外写 issue_title.txt / issue_body.md
                                   (GitHub Actions 用它开每日 Issue 提醒)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone


def env_flag(name, default="0"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def main():
    ap = argparse.ArgumentParser(description="BTC 永续每日日报 (手动发布版)")
    ap.add_argument("--mock", action="store_true", help="使用内置模拟数据 (离线演练)")
    ap.add_argument("--compact", action="store_true", help="单条速报模式")
    args = ap.parse_args()

    symbol = os.getenv("SYMBOL", "BTCUSDT")
    tz_off = int(os.getenv("TZ_OFFSET", "8"))
    compact = args.compact or env_flag("COMPACT")

    print(f"[bot] 标的={symbol}  模式={'单条速报' if compact else '完整日报'}"
          f"  mock={args.mock}  (手动发布版: 只生成不发布)")

    # ---- 1. 取数 ----
    if args.mock:
        from mock_data import load_mock
        bg, bn = load_mock()
        print("[bot] 使用内置模拟数据 (--mock, 文案带演练水印, 请勿发布)")
    else:
        from exchanges import fetch_binance, fetch_bitget
        print("[bot] 抓取 Bitget 主数据源 …")
        bg = fetch_bitget(symbol)
        print(f"[bot] Bitget OK: last={bg['ticker']['last']:.1f}"
              f"  日K={len(bg['d1'])}根  4H={len(bg['h4'])}根"
              f"  盘口={'有' if bg.get('book') else '无(已降级)'}")
        print("[bot] 抓取 币安 辅助验证源 …")
        bn = fetch_binance(symbol)
        if bn.get("error"):
            print(f"[bot] 币安不可用({bn['error']}): {str(bn.get('msg', ''))[:120]}"
                  " → 本期降级为 Bitget 单源")
        else:
            print(f"[bot] 币安 OK: last={bn['last']:.1f}")

    # ---- 2. 分析 ----
    from analysis import analyze
    a = analyze(bg, bn)
    lv = a["levels"]
    print("[bot] 4H关键位  压力:", [x["price"] for x in lv["res"]],
          " 支撑:", [x["price"] for x in lv["sup"]])

    # ---- 3. 生成复制包 ----
    from report import manual_pack
    now_local = datetime.now(timezone.utc) + timedelta(hours=tz_off)
    out = manual_pack(a, now_local, tz_off, compact=compact, mock=args.mock)

    # 先落盘, 再打印 (即使控制台输出被截断, 产物也已生成)
    report_file = os.getenv("REPORT_FILE", "last_report.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(out["pack"])

    arc = os.getenv("ARCHIVE_DIR", "").strip()
    if arc:
        os.makedirs(arc, exist_ok=True)
        for name in ("latest.txt", f"{now_local:%Y-%m-%d}.txt"):
            with open(os.path.join(arc, name), "w", encoding="utf-8") as f:
                f.write(out["pack"])

    if env_flag("WRITE_ISSUE"):
        with open("issue_title.txt", "w", encoding="utf-8") as f:
            f.write(out["issue_title"])
        with open("issue_body.md", "w", encoding="utf-8") as f:
            f.write(out["issue_body"])

    print("\n" + out["pack"])
    print(f"[bot] 文案包已保存: {report_file}  → 打开复制, 去 X 粘贴发布即可")
    if arc:
        print(f"[bot] 已存档: {arc}/latest.txt 与 {arc}/{now_local:%Y-%m-%d}.txt")
    if env_flag("WRITE_ISSUE"):
        print("[bot] 已写 Issue 素材: issue_title.txt / issue_body.md")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"[bot] 失败 ❌ {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
