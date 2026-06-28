#!/usr/bin/env python3
"""投资组合优化 CLI —— skill 的主入口。

把一组标的（美股 / A股 / 港股）优化成一份权重配置，并给出风险指标；
或用 ``--compare`` 在同一份数据上横向对比全部策略。数据源自动回退，免 API key。

示例:
    # 美股，最大夏普
    python scripts/optimize.py --tickers AAPL,MSFT,NVDA,JPM,KO --years 3

    # A股，最小方差 + 单一权重上限 30%
    python scripts/optimize.py --tickers 600519,000858,600036,000333 \
        --strategy min_variance --max-weight 0.3

    # 横向对比全部策略，输出 JSON
    python scripts/optimize.py --tickers AAPL,MSFT,GOOGL,AMZN,META --compare --format json

    # 用自带 CSV（离线 / 任意市场）
    python scripts/optimize.py --csv prices.csv --strategy risk_parity
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict

# 让脚本在任意工作目录下都能 import 到引擎包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_engine import PortfolioOptimizer  # noqa: E402
from portfolio_engine.utils import setup_logger  # noqa: E402

STRATEGIES = PortfolioOptimizer.available_strategies()


def _result_payload(weights: Dict[str, float], perf: Dict[str, Any]) -> Dict[str, Any]:
    """把 (weights, performance) 收敛成精简、可序列化的结果。"""
    nonzero = {k: round(float(v), 6) for k, v in sorted(weights.items(), key=lambda x: -x[1]) if v > 1e-4}
    conc = perf.get("concentration_metrics", {}) or {}
    return {
        "strategy": perf.get("strategy"),
        "weights": nonzero,
        "metrics": {
            "expected_annual_return": round(float(perf.get("expected_annual_return", 0)), 6),
            "annual_volatility": round(float(perf.get("annual_volatility", 0)), 6),
            "sharpe_ratio": round(float(perf.get("sharpe_ratio", 0)), 4),
            "sortino_ratio": round(float(perf.get("sortino_ratio", 0)), 4),
            "calmar_ratio": round(float(perf.get("calmar_ratio", 0)), 4),
            "max_drawdown": round(float(perf.get("max_drawdown", 0)), 6),
            "var_5_percent": round(float(perf.get("var_5_percent", 0)), 6),
            "cvar_5_percent": round(float(perf.get("cvar_5_percent", 0)), 6),
            "trading_days": int(perf.get("trading_days", 0)),
            "concentration": {
                "hhi": round(float(conc.get("hhi", 0)), 4),
                "effective_n": round(float(conc.get("effective_n", 0)), 2),
                "top5_weight": round(float(conc.get("top5_weight", 0)), 4),
            },
        },
    }


def _print_single(payload: Dict[str, Any]) -> None:
    print(f"\n=== 优化结果 [{payload['strategy']}] ===")
    print(f"{'标的':<12}{'权重':>10}")
    print("-" * 22)
    for ticker, w in payload["weights"].items():
        print(f"{ticker:<12}{w:>9.2%}")
    m = payload["metrics"]
    print("-" * 22)
    print(f"预期年化收益 : {m['expected_annual_return']:>8.2%}")
    print(f"年化波动率   : {m['annual_volatility']:>8.2%}")
    print(f"夏普比率     : {m['sharpe_ratio']:>8.3f}")
    print(f"Sortino 比率 : {m['sortino_ratio']:>8.3f}")
    print(f"Calmar 比率  : {m['calmar_ratio']:>8.3f}")
    print(f"最大回撤     : {m['max_drawdown']:>8.2%}")
    print(f"VaR(5%)/CVaR : {m['var_5_percent']:>8.2%} / {m['cvar_5_percent']:.2%}")
    print(f"有效持仓数   : {m['concentration']['effective_n']:>8.2f}  (前5大 {m['concentration']['top5_weight']:.0%})")


def _print_compare(results: Dict[str, Dict[str, Any]]) -> None:
    print(f"\n{'策略':<20}{'年化收益':>10}{'波动率':>10}{'夏普':>9}{'最大回撤':>10}")
    print("-" * 59)
    for name, p in results.items():
        m = p["metrics"]
        print(f"{name:<20}{m['expected_annual_return']:>9.2%} {m['annual_volatility']:>9.2%} "
              f"{m['sharpe_ratio']:>8.3f} {m['max_drawdown']:>9.2%}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="投资组合优化器（美股 / A股 / 港股，多源自动回退）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_argument_group("标的与数据")
    src.add_argument("--tickers", help="逗号分隔的代码，如 AAPL,MSFT 或 600519,000858。缺省用演示股票池")
    src.add_argument("--csv", help="改用本地 CSV 价格表（宽表：首列日期，其余每列一只标的收盘价）")
    src.add_argument("--market", choices=["US", "CN", "HK"], help="强制市场；缺省按代码自动识别")
    src.add_argument("--source", choices=["auto", "yfinance", "akshare", "eastmoney"], default="auto",
                     help="数据源（默认 auto：按市场自动选并回退）")
    src.add_argument("--adjust", choices=["qfq", "hfq", ""], default="qfq", help="复权方式（默认 qfq 前复权）")

    win = p.add_argument_group("时间窗口")
    win.add_argument("--years", type=int, help="回溯年数（默认 3，与 --start/--end 互斥）")
    win.add_argument("--start", dest="start_date", help="开始日期 YYYY-MM-DD")
    win.add_argument("--end", dest="end_date", help="结束日期 YYYY-MM-DD")

    opt = p.add_argument_group("优化参数")
    opt.add_argument("--strategy", choices=STRATEGIES, default="max_sharpe", help="优化策略（默认 max_sharpe）")
    opt.add_argument("--compare", action="store_true", help="对比全部策略而非只跑一种")
    opt.add_argument("--rf", type=float, default=0.02, help="无风险利率（年化，默认 0.02）")
    opt.add_argument("--max-weight", type=float, default=0.25, help="单一资产权重上限（默认 0.25）")
    opt.add_argument("--min-weight", type=float, default=0.0, help="单一资产权重下限（默认 0.0）")

    out = p.add_argument_group("输出")
    out.add_argument("--format", choices=["table", "json"], default="table", help="输出格式（默认 table）")
    out.add_argument("--output-dir", help="把权重 / 价格 / 指标落盘到该目录")
    out.add_argument("--quiet", action="store_true", help="减少日志")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(verbose=not args.quiet and args.format != "json")

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    optimizer = PortfolioOptimizer(
        risk_free_rate=args.rf,
        max_weight=args.max_weight,
        min_weight=args.min_weight,
        strategy=args.strategy,
        market=args.market,
        source=args.source,
        adjust=args.adjust,
    )
    fetch_kwargs: Dict[str, Any] = dict(
        tickers=tickers, years=args.years,
        start_date=args.start_date, end_date=args.end_date, csv=args.csv,
    )

    if args.compare:
        raw = optimizer.compare_strategies(**fetch_kwargs)
        results = {name: _result_payload(w, p) for name, (w, p) in raw.items()}
        if args.format == "json":
            print(json.dumps({"compare": results}, ensure_ascii=False, indent=2))
        else:
            _print_compare(results)
        return

    weights, perf = optimizer.optimize_portfolio(**fetch_kwargs)
    payload = _result_payload(weights, perf)

    if args.output_dir:
        prices = optimizer._resolve_prices(tickers, args.start_date, args.end_date, args.years, None, args.csv)
        paths = optimizer.save_results(weights, perf, prices, args.output_dir, tag=date.today().isoformat())
        payload["saved_files"] = paths

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_single(payload)
        if args.output_dir:
            print("\n已保存:", ", ".join(payload["saved_files"].values()))


if __name__ == "__main__":
    main()
