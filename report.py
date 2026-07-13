# -*- coding: utf-8 -*-
"""report.py — 中文推文生成

完整版格式对标"交易员晴天"式周报, 改为每日:
    #BTC 每日盘面报告‼️（M月D日 周X）
    【日线级别】1）… 2）…
    【4小时级别】1）… 2）…
    【关键位】压力/支撑 各三档 (三源共振 + 触碰验证)
    【量能与资金】成交额/费率/持仓/主动买盘/基差
    校验行 + 时间戳 + 免责声明

X 对 CJK 字符按 2 个权重计数(单条上限 280 权重), 超限自动按小节
拆成一条主推 + 楼中楼回复; 模板刻意不含链接(2026 按量计费下,
含链接的帖子单价约为纯文本的 13 倍)。
"""
from __future__ import annotations

WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TWEET_LIMIT = 280          # X 单条权重上限
PACK_LIMIT = 270           # 打包时预留 "（i/n）" 楼层编号的余量


# ------------------------------------------------------------ 加权字数 --
def weighted_len(s):
    """按 twitter-text v3 规则: 仅少数拉丁/标点区间计 1 权重, 其余(含 CJK/emoji)计 2"""
    w = 0
    for ch in s:
        o = ord(ch)
        if o <= 4351 or 8192 <= o <= 8205 or 8208 <= o <= 8223 or 8242 <= o <= 8247:
            w += 1
        else:
            w += 2
    return w


def split_thread(sections, limit=PACK_LIMIT):
    """把若干小节贪心打包成 ≤limit 的推文序列; 多条时追加（i/n）编号"""
    tweets, cur = [], ""
    for sec in sections:
        cand = (cur + "\n\n" + sec) if cur else sec
        if weighted_len(cand) <= limit:
            cur = cand
            continue
        if cur:
            tweets.append(cur)
        if weighted_len(sec) > limit:            # 单节超限 → 按行再拆
            buf = ""
            for ln in sec.split("\n"):
                c2 = (buf + "\n" + ln) if buf else ln
                if weighted_len(c2) <= limit:
                    buf = c2
                else:
                    if buf:
                        tweets.append(buf)
                    buf = ln
            cur = buf
        else:
            cur = sec
    if cur:
        tweets.append(cur)
    if len(tweets) > 1:
        n = len(tweets)
        tweets = [t + f"\n（{i + 1}/{n}）" for i, t in enumerate(tweets)]
    return tweets


# ------------------------------------------------------------ 小工具 --
def _lv(x, annotate=False):
    """价位 + 可选注记(触碰验证次数 / 巨墙 / 量能密集)"""
    if not annotate:
        return f"{x['price']}"
    tags = []
    t = x.get("touches", 0)
    if t >= 5:
        tags.append("多次验证")
    elif t >= 2:
        tags.append(f"{t}次验证")
    if x.get("wall"):
        tags.append("巨墙" + (x.get("wallStr") or ""))
    elif x.get("hvn"):
        tags.append("量能密集")
    return f"{x['price']}" + (f"（{'·'.join(tags)}）" if tags else "")


def _rsi_tag(v):
    if v >= 70:
        return "超买，防回踩"
    if v <= 30:
        return "超卖，或有反抽"
    if v >= 55:
        return "偏强"
    if v <= 45:
        return "偏弱"
    return "中性"


def _funding_tag(pct):
    if pct >= 0.05:
        return "多头情绪偏热"
    if pct >= 0.005:
        return "中性偏多"
    if pct <= -0.005:
        return "空头付费"
    return "中性"


# ------------------------------------------------------------ 完整日报 --
def build_full(a, now_local, tz_off=8, long_post=False):
    m, d = now_local.month, now_local.day
    wd = WEEK[now_local.weekday()]
    title = f"#BTC 每日盘面报告‼️（{m}月{d}日 {wd}）"

    # ---- 日线级别 ----
    day = a["day"]
    e21, e50 = day["ema21"], day["ema50"]
    st = day["struct_text"]
    if day["dir"] == "bull":
        l1 = (f"1）日线多头结构（{st}），价格站上EMA21（{e21:.0f}）"
              f"与EMA50（{e50:.0f}），趋势偏强")
    elif day["dir"] == "bear":
        l1 = (f"1）日线空头结构（{st}），价格受压EMA21（{e21:.0f}）下方，"
              f"反弹先视为修复")
    else:
        l1 = (f"1）日线震荡结构（{st}），价格绕EMA21（{e21:.0f}）拉锯，"
              f"EMA50在{e50:.0f}，方向待日K实体收线选择")
    dr, ds = a["day_levels"]["res"], a["day_levels"]["sup"]
    l2 = (f"2）上方观察{dr[0]['price']}：日K实体收上则打开空间，目标{dr[1]['price']}；"
          f"下方{ds[0]['price']}为多空分界，实体跌破看{ds[1]['price']}")
    day_sec = "【日线级别】\n" + l1 + "\n" + l2

    # ---- 4小时级别 ----
    h4 = a["h4"]
    rsi_v = h4["rsi"]
    if h4["ranging"]:
        h1 = (f"1）4小时于{h4['range_lo']:.0f}-{h4['range_hi']:.0f}箱体震荡"
              f"约{h4['range_days']:.0f}天，上沿测试{h4['touch_top']}次、"
              f"下沿{h4['touch_bot']}次")
        if h4["touch_top"] >= 4:
            h1 += "，上沿压力趋于钝化"
    elif h4["dir"] == "bull":
        h1 = (f"1）4小时多头排列（EMA21 {h4['ema21']:.0f} > EMA50 {h4['ema50']:.0f}），"
              f"短线结构偏多")
    elif h4["dir"] == "bear":
        h1 = (f"1）4小时空头排列（EMA21 {h4['ema21']:.0f} < EMA50 {h4['ema50']:.0f}），"
              f"短线结构偏空")
    else:
        h1 = (f"1）4小时均线粘合（EMA21 {h4['ema21']:.0f}／EMA50 {h4['ema50']:.0f}），"
              f"短线方向未选择")
    h1 += f"；RSI14={rsi_v:.0f}（{_rsi_tag(rsi_v)}）"
    of = a.get("orderflow")
    if of:
        h2 = f"2）盘口±0.5%买盘占比{of['bidSharePct']:.1f}%（{of['bias']}）"
        s = of.get("strongest")
        if s:
            is_ask = s["side"] == "ask"
            h2 += (f"；最强{'卖墙' if is_ask else '买墙'}{s['price']}"
                   f"（≈{s['notionalStr']}，{'压制' if is_ask else '托底'}）")
    else:
        h2 = "2）盘口深度本期不可用，位阶由枢轴×量能分布给出"
    h4_sec = "【4小时级别】\n" + h1 + "\n" + h2

    # ---- 关键位 ----
    src = "（Bitget×币安交叉验证）" if a.get("check") else "（Bitget，币安校验暂不可用）"
    res, sup = a["levels"]["res"], a["levels"]["sup"]
    lv_sec = ("【关键位】" + src
              + "\n压力：" + " / ".join(_lv(x, i == 0) for i, x in enumerate(res))
              + "\n支撑：" + " / ".join(_lv(x, i == 0) for i, x in enumerate(sup)))

    # ---- 量能与资金 ----
    v = a["vol"]
    lines = []
    ln = f"24h成交额{v['v24'] / 1e8:.0f}亿U"
    if v.get("ratio7"):
        r = v["ratio7"]
        tag = "放量" if r >= 130 else ("缩量" if r <= 70 else "量能平稳")
        ln += f"，为7日均值的{r:.0f}%（{tag}）"
    lines.append(ln)
    if v.get("funding") is not None:
        fp = v["funding"] * 100
        ln = f"资金费率{fp:+.4f}%（{_funding_tag(fp)}）"
    else:
        ln = "资金费率暂缺"
    if v.get("oi"):
        ln += f"｜持仓{v['oi'] / 1e4:.1f}万BTC"
        if v.get("oi_chg") is not None:
            ln += f"（24h{v['oi_chg']:+.1f}%）"
    lines.append(ln)
    extra = []
    if v.get("taker") is not None:
        t = v["taker"]
        ttag = "买盘占优" if t >= 53 else ("卖压占优" if t <= 47 else "买卖均衡")
        extra.append(f"主动买盘{t:.0f}%（{ttag}）")
    if v.get("basis") is not None:
        extra.append(f"基差{v['basis']:+.2f}%")
    if extra:
        lines.append("｜".join(extra))
    vol_sec = "【量能与资金】\n" + "\n".join(lines)

    # ---- 校验 + 尾注 ----
    ck = a.get("check")
    if ck:
        mark = "✅" if ck["ok"] else "⚠️偏离"
        c_line = (f"校验：Bitget {ck['bg']:.0f} / 币安 {ck['bn']:.0f}"
                  f"（差{ck['diff']:+.2f}% {mark}）")
    else:
        c_line = "校验：币安数据源本期不可用，报告为Bitget单源"
    tail = f"{now_local:%H:%M} UTC+{tz_off}｜自动播报·仅供参考·非投资建议"
    end_sec = c_line + "\n" + tail

    sections = [title, day_sec, h4_sec, lv_sec, vol_sec, end_sec]
    if long_post:
        return ["\n\n".join(sections)]
    return split_thread(sections)


# ------------------------------------------------------------ 单条速报 --
def build_compact(a, now_local, tz_off=8):
    p = a["price"]
    chg = a.get("chg24")
    res, sup = a["levels"]["res"], a["levels"]["sup"]
    v = a["vol"]
    one = {
        "bull": "日线多头结构，回踩关注支撑承接",
        "bear": "日线空头结构，反弹关注压力压制",
        "range": "日线震荡，盯区间边沿的突破与回收",
    }[a["day"]["dir"]]
    lines = [f"#BTC 每日速报（{now_local.month}/{now_local.day}）",
             f"现价{p:.0f}" + (f"（24h{chg:+.1f}%）" if chg is not None else ""),
             "压力 " + "/".join(str(x["price"]) for x in res),
             "支撑 " + "/".join(str(x["price"]) for x in sup)]
    ln = f"量能{v['v24'] / 1e8:.0f}亿U"
    if v.get("ratio7"):
        ln += f"·7日{v['ratio7']:.0f}%"
    if v.get("funding") is not None:
        ln += f"｜费率{v['funding'] * 100:+.3f}%"
    lines += [ln, one, "自动播报·非投资建议"]
    text = "\n".join(lines)
    # 速报必须单条: 极端情况下裁掉注记行保长度
    while weighted_len(text) > TWEET_LIMIT and len(lines) > 5:
        lines.pop(-2)
        text = "\n".join(lines)
    return text


# ------------------------------------------------- 手动发布版打包 --
SEP = "─" * 26


def manual_pack(a, now_local, tz_off=8, compact=False, mock=False):
    """生成给"人"用的复制包:
    · pack        写进 last_report.txt / reports/ 的纯文本, 带复制说明
    · issue_title / issue_body  给 GitHub Issue 用 (代码块自带复制按钮)
    """
    date_cn = f"{now_local.month}月{now_local.day}日"
    p = a["price"]
    chg = a.get("chg24")
    chg_txt = f"（24h{chg:+.1f}%）" if chg is not None else ""
    warn = "⚠️【演练数据, 请勿发布】" if mock else ""
    title = f"{warn}📋 BTC日报 {date_cn} · 现价{p:.0f}{chg_txt}"

    if compact:
        text = build_compact(a, now_local, tz_off)
        pack = (f"{warn}BTC 每日速报 · {now_local:%m-%d %H:%M} UTC+{tz_off}\n"
                f"复制下面整段, 粘贴到 X 直接发布:\n{SEP}\n{text}\n{SEP}\n")
        body = (f"{warn}今天的速报已生成（{now_local:%H:%M} UTC+{tz_off}）。"
                f"复制下方代码块内容, 粘贴到 X 发布即可。\n\n```text\n{text}\n```\n")
        return {"issue_title": title, "issue_body": body, "pack": pack}

    full = build_full(a, now_local, tz_off, long_post=True)[0]
    thread = build_full(a, now_local, tz_off)

    pack_lines = [
        f"{warn}BTC 每日盘面日报 · 生成于 {now_local:%m-%d %H:%M} UTC+{tz_off}",
        "",
        "◆ 方式一 · 整篇长文：有长文权限（Premium）就复制这段一条发",
        SEP, full, SEP, "",
        f"◆ 方式二 · 分楼串：共 {len(thread)} 条, 在 X 里先发第 1 条,",
        "  再对它点“回复”逐条粘贴（或写作页用“+”号加楼层）",
    ]
    for i, t in enumerate(thread, 1):
        pack_lines += [SEP + f" 第 {i}/{len(thread)} 条", t]
    pack_lines += [SEP, ""]
    pack = "\n".join(pack_lines)

    body_parts = [
        f"{warn}今天的日报已生成（{now_local:%H:%M} UTC+{tz_off}）。"
        "复制下方代码块内容, 粘贴到 X 发布即可（网页版代码块右上角有复制按钮, "
        "App 内长按全选）。\n",
        "**整篇版**（有长文权限直接一条发）：\n",
        f"```text\n{full}\n```\n",
        "<details><summary><b>分条版</b>（无长文权限时点开, 逐条回复串成楼）"
        "</summary>\n",
    ]
    for i, t in enumerate(thread, 1):
        body_parts.append(f"第 {i} 条：\n\n```text\n{t}\n```\n")
    body_parts.append("</details>\n")
    body = "\n".join(body_parts)
    return {"issue_title": title, "issue_body": body, "pack": pack}
