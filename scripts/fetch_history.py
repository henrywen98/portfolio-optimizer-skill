#!/usr/bin/env python3
"""拉取场内 ETF 的前复权日线，缓存成 CSV。只依赖标准库。

主数据源是腾讯 `web.ifzq.gtimg.cn`：免 key、不封 IP，返回前复权价。
东财的历史接口（push2his.eastmoney.com）在部分网络下会被 DNS 劫持，所以不作主源。

腾讯接口有两个必须绕开的坑：

1. 它是**从 end 往回数 count 条**，start 基本被忽略。想拿全历史只能把 end 一步步往前挪着翻页。
2. count 上限约 800。传 1000/2000 会**静默只返 640 条**（不报错），传 3000+ 才报 `param error`。
   所以这里固定用 640，宁可多翻几页也不踩静默截断。

用法::

    python3 fetch_history.py --codes 510300,511260,518880 --start 2014-01-01 --out ../data
    python3 fetch_history.py --probe 510300,159915        # 只看各代码的真实起止日期
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import sys
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
}
# 腾讯单次返回上限。超过约 800 会静默截断到 640，所以固定用安全值。
PAGE = 640
MAX_PAGES = 40  # 640 * 40 ≈ 25600 个交易日，远超任何 ETF 的寿命，纯粹防死循环


def market_prefix(code: str) -> str:
    """场内代码 -> 腾讯的市场前缀。

    5 / 6 开头是上交所（ETF 多为 51x/52x/56x/58x，黄金 518），其余（1 开头的
    15x/16x）是深交所。
    """
    return "sh" if code[0] in "56" else "sz"


def _get(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def _page(symbol: str, end: str, count: int = PAGE) -> List[list]:
    """取截至 ``end`` 的最后 ``count`` 根前复权日线。"""
    url = f"{TENCENT_URL}?param={symbol},day,,{end},{count},qfq"
    data = _get(url)
    if data.get("msg"):
        raise RuntimeError(f"{symbol} 接口报错: {data['msg']}")
    node = (data.get("data") or {}).get(symbol) or {}
    return node.get("qfqday") or node.get("day") or []


def fetch_series(code: str, start: str, end: str = "2030-12-31",
                 pause: float = 0.3) -> List[Tuple[str, float]]:
    """往回翻页取 ``code`` 从 ``start`` 到 ``end`` 的收盘价序列（日期升序）。

    Returns:
        ``[(YYYY-MM-DD, close), ...]``，已去重、按日期升序。
    """
    symbol = market_prefix(code) + code
    seen: Dict[str, float] = {}
    cursor = end

    for _ in range(MAX_PAGES):
        rows = _page(symbol, cursor)
        if not rows:
            break
        for row in rows:
            date, close = row[0], row[2]  # [日期, 开, 收, 高, 低, 量]
            try:
                seen[date] = float(close)
            except (TypeError, ValueError):
                continue
        oldest = min(r[0] for r in rows)
        if oldest <= start:
            break
        # 再往前翻一页：把游标挪到本页最早一天的前一天
        prev = _prev_day(oldest)
        if prev == cursor:  # 没有推进，说明到头了
            break
        cursor = prev
        time.sleep(pause)

    out = sorted((d, p) for d, p in seen.items() if d >= start)
    return out


def _prev_day(date: str) -> str:
    """``2014-05-23`` -> ``2014-05-22``（纯字符串日期运算，不引第三方库）。"""
    import datetime

    d = datetime.date.fromisoformat(date) - datetime.timedelta(days=1)
    return d.isoformat()


def probe(code: str) -> Optional[Tuple[str, str, int]]:
    """探测一个代码的真实数据起止与条数；取不到返回 None。"""
    try:
        series = fetch_series(code, start="1990-01-01")
    except Exception as exc:  # noqa: BLE001
        print(f"  {code}  异常 {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if not series:
        return None
    return series[0][0], series[-1][0], len(series)


def write_csv(path: str, series_by_code: Dict[str, List[Tuple[str, float]]]) -> int:
    """把多只标的的收盘价写成宽表 CSV（首列 date，其余每列一只）。

    只保留**所有标的都有报价**的交易日，避免后续回测在缺失日上做无声的前向填充。
    """
    codes = sorted(series_by_code)
    per_code = {c: dict(series_by_code[c]) for c in codes}
    common = set.intersection(*(set(per_code[c]) for c in codes)) if codes else set()
    dates = sorted(common)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date"] + codes)
        for d in dates:
            w.writerow([d] + [f"{per_code[c][d]:.6f}" for c in codes])
    return len(dates)


def main() -> None:
    p = argparse.ArgumentParser(description="拉取场内 ETF 前复权日线并缓存")
    p.add_argument("--codes", help="逗号分隔的 6 位代码")
    p.add_argument("--start", default="2014-01-01", help="起始日期（默认 2014-01-01）")
    p.add_argument("--end", default="2030-12-31", help="结束日期")
    p.add_argument("--out", default="../data/prices.csv", help="输出 CSV 路径")
    p.add_argument("--probe", help="只探测这些代码的真实数据起止，不落盘")
    args = p.parse_args()

    if args.probe:
        print(f"{'代码':<8}{'起':<12}{'止':<12}{'条数':>6}")
        for code in [c.strip() for c in args.probe.split(",") if c.strip()]:
            got = probe(code)
            if got is None:
                print(f"{code:<8}❌ 无数据")
            else:
                first, last, n = got
                print(f"{code:<8}{first:<12}{last:<12}{n:>6}")
        return

    if not args.codes:
        p.error("需要 --codes 或 --probe")

    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    series_by_code: Dict[str, List[Tuple[str, float]]] = {}
    failed: List[str] = []
    for code in codes:
        try:
            s = fetch_series(code, start=args.start, end=args.end)
        except Exception as exc:  # noqa: BLE001
            print(f"{code}: 取数失败 {type(exc).__name__}: {exc}", file=sys.stderr)
            failed.append(code)
            continue
        if not s:
            print(f"{code}: 无数据", file=sys.stderr)
            failed.append(code)
            continue
        series_by_code[code] = s
        print(f"{code}: {len(s)} 行  {s[0][0]} ~ {s[-1][0]}")

    if failed:
        raise SystemExit(f"以下代码取数失败，终止（不出半份数据）: {failed}")

    n = write_csv(args.out, series_by_code)
    print(f"\n已写入 {args.out}：{n} 个共同交易日 × {len(series_by_code)} 只")
    if n == 0:
        raise SystemExit("共同交易日为 0，检查各标的历史是否有重叠区间")


if __name__ == "__main__":
    main()
