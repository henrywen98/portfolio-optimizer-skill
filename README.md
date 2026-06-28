# Portfolio Optimizer Skill

> A **no-API-key, multi-market portfolio optimizer** that runs as a [Claude Code](https://claude.com/claude-code) skill — turn a list of tickers into an optimal weight allocation plus a full risk report, across **US stocks, China A-shares, and Hong Kong stocks**, with free data and zero setup.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-d97757.svg)
![No API key](https://img.shields.io/badge/data-no%20API%20key-brightgreen.svg)

**English** · [简体中文](README.zh-CN.md)

> ⚠️ For **education / research only**. Nothing here is investment advice.

---

## What it is

This repo **is** a Claude Code skill. Once installed, you drive it in plain language — Claude reads your intent, runs the bundled engine, and explains the result:

- *"Optimize my portfolio of AAPL, MSFT, NVDA for max Sharpe"*
- *"帮我把 600519,000858,600036 做个最小方差配置，单只不超过 30%"*
- *"Compare a few allocation strategies for these tickers and tell me which has the best Sharpe"*

No command memorization, no data plumbing, no exchange/API keys. It works the same whether you point it at Apple or at Kweichow Moutai.

## Why this exists

Asking a general-purpose LLM to "write some PyPortfolioOpt code" gets you the *math* — but it stalls the moment you need **real prices**. Free US data gets rate-limited from cloud IPs; A-share and Hong Kong tickers need exchange-prefix / `secid` resolution that's fiddly to get right; and every ad-hoc script reinvents the fallback logic. This skill is the part that's annoying to reproduce:

| | This skill | Plain "ask Claude to write code" | A typical GitHub optimizer |
|---|:---:|:---:|:---:|
| Runs as a Claude Code skill (natural language) | ✅ | — | — |
| **US + A-shares + HK**, auto market detection | ✅ | ⚠️ you wire it | usually one market |
| **No API key**, multi-source auto-fallback | ✅ | ❌ stalls on data | varies |
| 5 strategies + side-by-side compare | ✅ | ⚠️ partial | usually 1–2 |
| Full risk report (Sharpe/Sortino/Calmar/VaR/CVaR/drawdown/concentration) | ✅ | ⚠️ partial | varies |
| Rolling-rebalance backtest with trading costs | ✅ | ❌ | sometimes |
| Offline CSV mode (any market, no network) | ✅ | ❌ | rare |

The data layer is the moat: `auto` mode picks a source by market and falls back through **yfinance → akshare → East Money (direct) → local CSV** until one works — no key, anywhere.

## Install

It's a standard Claude Code skill — drop it in your skills directory:

```bash
git clone https://github.com/henrywen98/portfolio-optimizer-skill \
  ~/.claude/skills/portfolio-optimizer
cd ~/.claude/skills/portfolio-optimizer
pip install -r requirements.txt
```

Restart Claude Code and just ask it to optimize a portfolio — the skill triggers on intent. You can also run the engine directly (below) without Claude at all.

## Quick start (CLI / no Claude needed)

```bash
# US stocks, max Sharpe
python scripts/optimize.py --tickers AAPL,MSFT,NVDA,JPM,KO --strategy max_sharpe --years 3

# A-shares, min variance, cap any single name at 30%
python scripts/optimize.py --tickers 600519,000858,600036 --strategy min_variance --max-weight 0.3

# Compare every strategy side by side (JSON out)
python scripts/optimize.py --tickers AAPL,MSFT,GOOGL,AMZN,META --compare --format json

# Offline: feed your own price CSV (any market)
python scripts/optimize.py --csv prices.csv --strategy risk_parity
```

Rolling-rebalance backtest with trading costs (advanced):

```bash
python scripts/backtest.py --tickers AAPL,MSFT,NVDA,JPM,KO --years 5 \
    --strategy max_sharpe --lookback 252 --rebalance 63
```

## Strategies

| Strategy | `--strategy` | In one line |
|---|---|---|
| Max Sharpe | `max_sharpe` | Highest excess return per unit of risk (default) |
| Min Variance | `min_variance` | Lowest portfolio volatility on the feasible set |
| Risk Parity | `risk_parity` | Every holding contributes equal risk (convex risk-budgeting) |
| Max Diversification | `max_diversification` | Maximize the diversification ratio |
| Equal Weight | `equal_weight` | Naive 1/N benchmark |

## Data sources (no API key)

`auto` mode chooses by market and falls back until one succeeds:

| Market | Ticker example | Source order |
|---|---|---|
| US | `AAPL`, `MSFT` | yfinance → akshare → East Money |
| China A-share | `600519`, `000858` | akshare → East Money → yfinance |
| Hong Kong | `00700`, `09988` | akshare → East Money → yfinance |
| Any (offline) | `--csv prices.csv` | local CSV, no network |

## Python API

```python
from portfolio_engine import PortfolioOptimizer

opt = PortfolioOptimizer(strategy="max_sharpe", max_weight=0.3)
weights, perf = opt.optimize_portfolio(tickers=["AAPL", "MSFT", "NVDA"], years=3)

print(weights)               # {'AAPL': 0.31, ...}
print(perf["sharpe_ratio"])  # plus Sortino / Calmar / VaR / CVaR / drawdown / concentration
```

## Project structure

| Path | Role |
|---|---|
| `SKILL.md` | **Skill entry** — triggering, usage, guidance for Claude |
| `portfolio_engine/` | Engine: optimizer, data fetch, market detection, constraints, backtest |
| `scripts/optimize.py` | CLI — single strategy + `--compare` |
| `scripts/backtest.py` | CLI — rolling-window optimize + periodic rebalance |
| `references/` | Deep-dive docs (strategies / metrics / data / constraints / backtesting) |
| `tests/` | Offline pytest suite (no network) |

## How it was built

This skill was refactored from a single-market A-share tool and then **hardened with an evaluation loop** (Claude-with-skill vs. a from-scratch baseline, graded across many prompts). That loop earned its keep: on a low-correlation portfolio the baseline *beat* the skill because the old iterative risk-parity routine was zeroing out valid assets on ill-conditioned covariance. The fix — switching to the convex Spinu/Maillard risk-budgeting formulation (`minimize ½·wᵀΣw − (1/n)·Σ ln wᵢ`) — now keeps every asset long-only with equalized risk contributions, and ships with a regression test. A skill is only worth triggering if it's never *worse* than just asking the model directly.

See [`references/`](references/) for the strategy math, risk-metric definitions, the multi-source data design, and the backtest model.

## Roadmap

- More markets (LSE / TSE) behind the same auto-fallback
- Black-Litterman / views-based allocation
- Factor-tilt constraints

Contributions welcome — open an issue or PR.

## License

[MIT](LICENSE) · © 2025 Henry Wen

---

If this saved you from wiring up yet another data fetcher, a ⭐ helps other people find it.
