# asset-allocation

A Claude Code skill that turns "I have X money and can stomach about a Y% loss" into a
concrete ETF portfolio — and then checks whether that Y% promise actually holds up.

Built for China A-share retail investors. Covers A-share broad indices, government bonds,
gold, and overseas equity (QDII), all as exchange-traded funds.

## What makes it different

Most allocation tools maximize Sharpe ratio and report backtest numbers. Two problems with
that, both of which this skill handles:

**1. A drawdown budget has no closed-form solution.** Max drawdown is not a convex function
of the weights, so you cannot solve for it — you have to run the weights through real price
history. This skill does a grid search and backtests every candidate, then keeps only the
ones that stayed inside your budget.

**2. One realized drawdown is not a distribution.** The max drawdown your portfolio happened
to have over one historical path is a single draw with an effective sample size of 1. Using it
as a hard limit is optimistic. This skill also runs a stationary block bootstrap to estimate
the *distribution* of drawdowns.

How much does that matter? On a 2014-2026 A-share dataset:

| Portfolio | Realized max drawdown | Bootstrap p95 |
|---|---|---|
| 25% bond / 25% Nasdaq / 20% CSI300 / 20% gold / 10% dividend | -19.2% | **-25.5%** |
| 100% CSI 300 | -47.1% | **-72.0%** |

The realized figure understates the risk by roughly 6 percentage points. Note that the
bootstrap p95 for CSI 300, **-72.0%**, is very close to its actual 2008 drawdown of -72.3% —
a crash that is not in the sample window at all.

## It refuses rather than fakes

- If no portfolio can meet your drawdown budget, it raises an error telling you the most
  conservative one still draws down X% — it never quietly loosens the constraint to return
  something.
- If your backtest window does not cover the 2015 A-share crash, it refuses to run. A drawdown
  limit calibrated only on a bull market is a false promise.

## It does not predict

No sector calls, no market timing, no "we like AI infrastructure this quarter." Weights come
from your risk budget. Web search is used only to decide whether to enter all at once or
average in, and to write the risk section.

## Install

```bash
git clone https://github.com/henrywen98/asset-allocation.git \
  ~/.claude/skills/asset-allocation
```

## Use

```bash
# 1. Fetch price history (pure stdlib — no dependencies needed)
python3 scripts/fetch_history.py \
  --codes 510300,510500,510880,511010,518880,513100 \
  --start 2014-01-01 --out data/core_prices.csv

# 2. Solve for weights under a drawdown budget
python3 scripts/allocate.py \
  --prices data/core_prices.csv \
  --specs core_specs.json \
  --max-dd 0.20 \
  --horizon-years 5
```

`allocate.py` needs pandas and numpy. `fetch_history.py` needs nothing.

Or just ask Claude Code: "帮我配个资产组合，最多能亏 20%".

## Output

- `weights` — target weight per ETF
- `metrics` — CAGR, volatility, Sharpe, realized max drawdown
- `robustness` — the window split into thirds, each checked separately, so a portfolio that
  only worked in one stretch gets flagged
- `holding_period` — distribution of returns if you hold for N years, including probability
  of loss. This matters more than max drawdown when your horizon is short.
- `frontier` — best return available at each drawdown level, so you can see what loosening
  the budget actually buys you

## Data

Tencent's quote endpoint (`web.ifzq.gtimg.cn`). No API key, no IP blocking, forward-adjusted
prices. East Money's history endpoint is not used as the primary source — it gets
DNS-blackholed on some networks.

## Not investment advice

This is a research and planning tool. Backtests do not predict future returns.

## License

MIT
