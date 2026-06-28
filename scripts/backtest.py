#!/usr/bin/env python3
"""滚动再平衡回测 CLI（进阶）。

在历史价格上做「滚动窗口优化 + 定期再平衡」的回测，计入交易成本，给出年化收益 /
夏普 / 最大回撤 / Alpha / 换手成本等。支持单策略或 ``--compare`` 多策略对比。

示例:
    # 美股 5 年，最大夏普，季度再平衡
    python scripts/backtest.py --tickers AAPL,MSFT,NVDA,JPM,KO --years 5 \
        --strategy max_sharpe --lookback 252 --rebalance 63

    # 多策略对比（JSON）
    python scripts/backtest.py --tickers 600519,000858,600036,000333 --years 5 \
        --compare --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from portfolio_engine import Market  # noqa: E402
from portfolio_engine.backtest import (  # noqa: E402
    Backtester,
    BacktestConfig,
    OptimizationStrategy,
    generate_backtest_report,
)
from portfolio_engine.data import DataFetcher, get_default_tickers, load_prices_csv  # noqa: E402
from portfolio_engine.utils import setup_logger  # noqa: E402

STRATEGIES = [s.value for s in OptimizationStrategy]


def _resolve_prices(args) -> pd.DataFrame:
    """根据 tickers/csv + 时间窗口取价格表。"""
    if args.csv:
        tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
        return load_prices_csv(args.csv, tickers=tickers)
    tickers = (
        [t.strip() for t in args.tickers.split(",")]
        if args.tickers
        else get_default_tickers(args.market or Market.US)
    )
    if args.start_date and args.end_date:
        start, end = args.start_date, args.end_date
    else:
        years = args.years or 5
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=years * 365)).isoformat()
    mkt = Market[args.market] if args.market else None
    return DataFetcher(source=args.source, adjust=args.adjust).fetch_prices(tickers, start, end, market=mkt)


def _round_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in metrics.items()}


def _config(args, strategy: OptimizationStrategy) -> BacktestConfig:
    return BacktestConfig(
        lookback_days=args.lookback,
        rebalance_frequency=args.rebalance,
        commission_rate=args.commission,
        stamp_duty=args.stamp_duty,
        slippage=args.slippage,
        strategy=strategy,
        risk_free_rate=args.rf,
        max_weight=args.max_weight,
        min_weight=args.min_weight,
        initial_capital=args.capital,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="滚动再平衡回测（进阶）",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tickers", help="逗号分隔代码，缺省用演示池")
    p.add_argument("--csv", help="本地价格表（宽表）")
    p.add_argument("--market", choices=["US", "CN", "HK"], help="强制市场；缺省自动识别")
    p.add_argument("--source", choices=["auto", "yfinance", "akshare", "eastmoney"], default="auto")
    p.add_argument("--adjust", choices=["qfq", "hfq", ""], default="qfq")
    p.add_argument("--years", type=int, help="回溯年数（默认 5；回测需要较长历史）")
    p.add_argument("--start", dest="start_date", help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", dest="end_date", help="结束日期 YYYY-MM-DD")
    p.add_argument("--strategy", choices=STRATEGIES, default="max_sharpe")
    p.add_argument("--compare", action="store_true", help="对比全部策略")
    p.add_argument("--lookback", type=int, default=252, help="优化窗口天数（默认 252）")
    p.add_argument("--rebalance", type=int, default=63, help="再平衡周期天数（默认 63 ≈ 季度）")
    p.add_argument("--rf", type=float, default=0.02)
    p.add_argument("--max-weight", type=float, default=0.25)
    p.add_argument("--min-weight", type=float, default=0.0)
    p.add_argument("--capital", type=float, default=1_000_000, help="初始资金")
    p.add_argument("--commission", type=float, default=0.0003, help="佣金率")
    p.add_argument("--stamp-duty", type=float, default=0.001, help="印花税（仅卖出，A股）")
    p.add_argument("--slippage", type=float, default=0.001, help="滑点")
    p.add_argument("--benchmark", help="基准代码（缺省用等权组合）")
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.add_argument("--output-dir", help="保存净值曲线等")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(verbose=not args.quiet and args.format != "json")
    prices = _resolve_prices(args)

    if args.compare:
        results = Backtester(_config(args, OptimizationStrategy.MAX_SHARPE)).compare_strategies(
            prices, benchmark_ticker=args.benchmark
        )
        if args.format == "json":
            print(json.dumps({s: _round_metrics(r.metrics) for s, r in results.items()},
                             ensure_ascii=False, indent=2))
        else:
            print(generate_backtest_report(results).to_string(index=False))
        return

    strat = OptimizationStrategy(args.strategy)
    result = Backtester(_config(args, strat)).run(prices, benchmark_ticker=args.benchmark)

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        result.portfolio_values.to_csv(out / "portfolio_values.csv")
        if not result.weights_history.empty:
            result.weights_history.to_csv(out / "weights_history.csv")

    if args.format == "json":
        print(json.dumps({"strategy": strat.value, "metrics": _round_metrics(result.metrics)},
                         ensure_ascii=False, indent=2))
    else:
        m = result.metrics
        print(f"\n=== 回测结果 [{strat.value}] ===")
        print(f"年化收益 {m['annual_return']:.2%} · 夏普 {m['sharpe_ratio']:.2f} · "
              f"最大回撤 {m['max_drawdown']:.2%} · Alpha {m['alpha']:.2%}")
        print(f"再平衡 {m['rebalance_count']} 次 · 交易 {m['total_trades']} 笔 · "
              f"总成本 {m['total_trading_cost']:.0f} ({m['cost_ratio']:.2%})")


if __name__ == "__main__":
    main()
