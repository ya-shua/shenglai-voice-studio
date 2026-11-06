# -*- coding: utf-8 -*-
"""用量记账：每次 TTS 合成记一笔（时间/平台/字数/用途），聚合出每日柱状图数据。

- 存储：data_root()/usage.jsonl，一行一条 JSON（追加写，面板重启不丢）。
- 费用：各平台真实账单在各自控制台，这里只按「单价表」估——单价存 config.json
  的 usage_prices（元/千字符，默认全 0 = 只统计量不估钱）。
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from lib import config


def _path() -> Path:
    return config.data_root() / "usage.jsonl"


def record(provider_id: str, chars: int, kind: str = "tts") -> None:
    """记一笔合成用量。任何失败都不影响主流程（统计是锦上添花）。"""
    try:
        entry = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "p": provider_id,
                 "c": int(chars), "k": kind}
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _prices() -> dict:
    """单价表（元/千字符）：config.json 的 usage_prices，默认全 0。"""
    try:
        cfg = json.loads((config.data_root() / "config.json").read_text(encoding="utf-8"))
        return cfg.get("usage_prices") or {}
    except Exception:
        return {}


def aggregate(days: int = 14) -> dict:
    """聚合最近 N 天：按日按平台累计字数与次数 + 今日统计 + 估算费用。"""
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    today = time.strftime("%Y-%m-%d")
    per_day = defaultdict(lambda: defaultdict(int))   # date -> provider -> chars
    counts = defaultdict(lambda: defaultdict(int))    # date -> provider -> count
    try:
        for line in _path().read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            day = str(e.get("t", ""))[:10]
            if day < since or day > today:
                continue
            per_day[day][str(e.get("p", "?"))] += int(e.get("c", 0))
            counts[day][str(e.get("p", "?"))] += 1
    except FileNotFoundError:
        pass

    prices = _prices()
    days_out = []
    total_chars = 0
    total_count = 0
    est_cost = 0.0
    d = datetime.now() - timedelta(days=days - 1)
    while d <= datetime.now():
        day = d.strftime("%Y-%m-%d")
        providers = per_day.get(day, {})
        chars = sum(providers.values())
        count = sum(counts.get(day, {}).values())
        cost = sum(pc / 1000.0 * float(prices.get(pp, 0)) for pp, pc in providers.items())
        est_cost += cost
        total_chars += chars
        total_count += count
        days_out.append({"date": day[5:], "chars": chars, "count": count,
                         "cost": round(cost, 4), "providers": providers})
        d += timedelta(days=1)

    today_p = per_day.get(today, {})
    return {
        "days": days_out,
        "today": {"count": sum(counts.get(today, {}).values()),
                  "chars": sum(today_p.values()),
                  "cost": round(sum(pc / 1000.0 * float(prices.get(pp, 0)) for pp, pc in today_p.items()), 4)},
        "total": {"chars": total_chars, "count": total_count, "cost": round(est_cost, 4)},
        "prices": prices,
    }
