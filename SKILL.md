---
name: portfolio-optimizer
description: >-
  Optimize a stock portfolio — decide how much weight to put on each ticker — across
  US stocks, China A-shares, and Hong Kong stocks, with no API key needed (free data
  via yfinance → akshare → CSV auto-fallback). Runs mean-variance and related strategies
  (max Sharpe, min variance, risk parity, max diversification, equal weight), reports
  risk metrics (Sharpe / Sortino / Calmar / VaR / CVaR / max drawdown / concentration),
  and can compare all strategies side by side. Use this WHENEVER the user wants to build
  or optimize an investment portfolio, decide asset allocation / position sizing / weights
  for a set of stocks, maximize Sharpe ratio, minimize volatility/risk, find the
  best split across tickers, compare allocation strategies, or analyze a portfolio's
  risk — even if they don't say the word "optimize". Triggers on things like
  "帮我把这几只股票配个最优权重", "这个组合怎么配夏普最高", "optimize my portfolio of AAPL MSFT NVDA",
  "美股加A股做个资产配置", "min variance allocation for these tickers", "how should I split my money
  across these stocks", "风险平价组合", "回测对比几个配置策略". Also covers sector constraints,
  transaction costs, and rolling-window backtests (advanced).
---

# Portfolio Optimizer

Turn a list of stock tickers into an optimal **weight allocation** plus a full risk
report — for **US stocks, China A-shares, and Hong Kong stocks** — using free data
sources that need no API key.

The heavy lifting lives in a bundled Python engine (`portfolio_engine/`) driven by one
CLI (`scripts/optimize.py`). Your job is to gather the user's intent, run the CLI, and
present the results clearly.

## When to use

Use this skill when the user wants to:
- Allocate weights across a set of stocks (asset allocation / position sizing).
- Maximize Sharpe ratio, minimize variance, or apply risk parity / max diversification / equal weight.
- Compare allocation strategies on the same universe.
- Get portfolio risk metrics (volatility, drawdown, VaR/CVaR, concentration).
- Backtest a rolling-rebalanced strategy, or add sector / transaction-cost constraints (advanced).

It works even when the user just lists tickers and asks "how should I split my money",
or names a market ("美股 + A股") without saying "optimize".

**Not for**: single-stock price lookups, fundamental analysis, news/sentiment, options
pricing, or live trading execution. This is allocation & risk analysis on historical prices.

> ⚠️ Educational/research tool. Past performance ≠ future results. Not investment advice —
> say so when presenting results.

## Setup (run once per environment)

The engine needs `pandas numpy scipy PyPortfolioOpt requests` plus at least one data
source (`yfinance` for US/global, `akshare` for A-share/HK/US). First check what's
available, and only install what's missing:

```bash
python3 -c "import pandas, numpy, scipy, pypfopt, requests; print('core OK')" 2>&1
python3 -c "import yfinance; print('yfinance OK')" 2>&1
python3 -c "import akshare; print('akshare OK')" 2>&1
```

If something is missing, install from the skill directory:

```bash
pip install -r requirements.txt
```

Use whatever Python has these installed (a project venv is fine). All commands below
assume your working directory is the skill root; otherwise pass the full path to
`scripts/optimize.py`.

## Workflow

1. **Collect inputs.** You need the **tickers** (or a price CSV) and ideally a strategy.
   If the user didn't specify, sensible defaults are: strategy `max_sharpe`, 3-year
   window, `--max-weight 0.25` (so no single name dominates). Detect the market
   automatically from the ticker format — don't ask unless it's ambiguous.
   - US: `AAPL`, `MSFT`, `BRK-B` · A-share: `600519`, `000858`, `300750` · HK: `00700`, `09988`
2. **Pick the strategy.** If the user is unsure which strategy fits, read
   `references/strategies.md` and recommend one (don't dump all options on them).
3. **Run the CLI** with `--format json` so you can parse the result reliably (see below).
4. **Present results** as a clean weights table + key metrics, and a one-line takeaway.
   Explain metrics in plain language if the user isn't a quant (see `references/metrics.md`).
5. **Offer next steps** when relevant: compare strategies (`--compare`), tighten the cap,
   add constraints, or backtest (`references/backtesting.md`).

## Running the optimizer

Always prefer `--format json` for parsing; then render a friendly table yourself.

```bash
# Single strategy (US), parse the JSON
python scripts/optimize.py --tickers AAPL,MSFT,NVDA,JPM,KO,JNJ --strategy max_sharpe \
  --years 3 --max-weight 0.3 --format json

# A-shares, minimum variance
python scripts/optimize.py --tickers 600519,000858,600036,000333,300750 \
  --strategy min_variance --years 3 --format json

# Compare ALL strategies on one universe
python scripts/optimize.py --tickers AAPL,MSFT,GOOGL,AMZN,META --compare --format json

# User-provided price data (offline / any market). CSV = wide table:
# first column dates, each other column a ticker's close price.
python scripts/optimize.py --csv prices.csv --strategy risk_parity --format json

# Save weights + prices + metrics to files
python scripts/optimize.py --tickers AAPL,MSFT,NVDA --output-dir ./out --format json
```

### Key flags

| Flag | Meaning | Default |
|------|---------|---------|
| `--tickers` | Comma-separated codes (auto-detects market) | demo pool |
| `--csv` | Use a local price table instead of fetching | — |
| `--market` | Force `US`/`CN`/`HK` (else auto-detect) | auto |
| `--source` | `auto` / `yfinance` / `akshare` / `eastmoney` | auto |
| `--strategy` | `max_sharpe`,`min_variance`,`risk_parity`,`max_diversification`,`equal_weight` | `max_sharpe` |
| `--compare` | Run every strategy and compare | off |
| `--years` | Look-back years (or use `--start`/`--end`) | 3 |
| `--rf` | Risk-free rate (annual) | 0.02 |
| `--max-weight` / `--min-weight` | Per-asset weight bounds | 0.25 / 0.0 |
| `--format` | `json` (parse) or `table` (human) | table |
| `--output-dir` | Save weights/prices/metrics | — |

### JSON shape

Single run → `{ "strategy", "weights": {ticker: w}, "metrics": {...} }`.
Compare → `{ "compare": { strategy: {weights, metrics}, ... } }`.
`metrics` includes `expected_annual_return, annual_volatility, sharpe_ratio,
sortino_ratio, calmar_ratio, max_drawdown, var_5_percent, cvar_5_percent,
trading_days, concentration{hhi, effective_n, top5_weight}`.

## Presenting results

Lead with the allocation, then the headline risk numbers, then a short takeaway.
Use the user's language. A good shape:

```
**最优权重 (max_sharpe, 近3年)**
| 标的 | 权重 |
|------|------|
| JNJ  | 30.0% |
| KO   | 29.1% |
| ...  | ...   |

预期年化收益 29.3% · 年化波动 12.8% · 夏普 2.14 · 最大回撤 -12.9%
有效持仓 3.9 只（前5大 100%）

一句话：组合偏向低波动的消费/医药，夏普很高但集中度也高——想更分散可调低 --max-weight。
```

Always note it's historical/educational, not advice.

## Data sources (no API key)

`auto` mode picks per market and falls back automatically:
US → yfinance, then akshare, then eastmoney-direct; A-share/HK → akshare/eastmoney first,
then yfinance; CSV always works offline. If a fetch returns nothing, the most common
causes are a wrong ticker format or a too-short window — see
`references/data-sources.md` for ticker formats per market and troubleshooting.

## Advanced

These exist in the engine but aren't the main flow — read the reference before using:
- **Sector constraints & transaction costs** → `references/constraints-and-costs.md`
- **Rolling-window backtesting** (`scripts/backtest.py`) → `references/backtesting.md`

## Reference files

- `references/strategies.md` — what each strategy optimizes and when to pick it.
- `references/metrics.md` — plain-language definitions of every risk metric.
- `references/data-sources.md` — ticker formats per market, source fallback, troubleshooting.
- `references/constraints-and-costs.md` — sector limits, commission/stamp-duty/slippage.
- `references/backtesting.md` — rolling rebalancing, the backtest CLI, and its outputs.

## Python API (if scripting is easier than the CLI)

```python
from portfolio_engine import PortfolioOptimizer
opt = PortfolioOptimizer(strategy="max_sharpe", max_weight=0.3)
weights, perf = opt.optimize_portfolio(tickers=["AAPL", "MSFT", "NVDA"], years=3)
# or compare: opt.compare_strategies(tickers=[...], years=3)
# or offline:  opt.optimize_portfolio(csv="prices.csv")
```
