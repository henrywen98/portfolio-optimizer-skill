# Portfolio Optimizer

> 多市场投资组合优化 **Claude Code Skill** —— 把一组标的（**美股 / A股 / 港股**）配成一份最优权重，并给出完整风险报告。免 API key，数据源自动回退。

⚠️ **仅供教育 / 研究用途，不构成任何投资建议。**

---

## 这是一个 Claude Code Skill

本仓库本身就是一个 skill，入口是 [`SKILL.md`](SKILL.md)。在 Claude Code 里直接用**自然语言**触发，无需记命令：

- “帮我把 AAPL,MSFT,NVDA 配个最大夏普权重”
- “这几只 A股 600519,000858,600036 做个最小方差配置，单只不超过 30%”
- “对比一下这几个标的的几种配置策略，哪个夏普最高”

Claude 会读取意图、调用下面的 CLI、再把结果讲清楚。

---

## 快速开始（直接用引擎 / CLI）

```bash
pip install -r requirements.txt

# 美股，最大夏普
python scripts/optimize.py --tickers AAPL,MSFT,NVDA,JPM,KO --strategy max_sharpe --years 3

# A股，最小方差
python scripts/optimize.py --tickers 600519,000858,600036 --strategy min_variance --years 3

# 横向对比全部策略
python scripts/optimize.py --tickers AAPL,MSFT,GOOGL --compare

# 用本地 CSV（离线 / 任意市场）
python scripts/optimize.py --csv prices.csv --strategy risk_parity
```

滚动再平衡回测（进阶）：

```bash
python scripts/backtest.py --tickers AAPL,MSFT,NVDA,JPM,KO --years 5 \
    --strategy max_sharpe --lookback 252 --rebalance 63
```

---

## 5 种优化策略

| 策略 | `--strategy` | 一句话 |
|------|--------------|--------|
| 最大夏普 | `max_sharpe` | 单位风险下追求最高超额收益（默认） |
| 最小方差 | `min_variance` | 在可行集里把组合波动率压到最低 |
| 风险平价 | `risk_parity` | 让每只标的对组合风险的贡献相等 |
| 最大分散化 | `max_diversification` | 最大化分散化比率，摊薄集中度 |
| 等权重 | `equal_weight` | 简单均分，作为对照基准 |

**数据源**：`auto` 模式按市场自动选择并回退 —— yfinance → akshare → 东财直连 → 本地 CSV，全程免 API key。

---

## 目录结构

| 路径 | 作用 |
|------|------|
| `SKILL.md` | **skill 入口**：触发条件、用法、给 Claude 的指引 |
| `portfolio_engine/` | 引擎包：优化器、数据获取、市场识别、约束、回测 |
| `scripts/optimize.py` | CLI：单策略优化 + `--compare` 多策略对比 |
| `scripts/backtest.py` | CLI：滚动窗口优化 + 定期再平衡回测 |
| `references/` | 进阶文档（策略 / 数据源 / 约束与成本 / 回测） |
| `tests/` | pytest 测试 |

---

## Python API

```python
from portfolio_engine import PortfolioOptimizer

opt = PortfolioOptimizer(strategy="max_sharpe", max_weight=0.3)
weights, perf = opt.optimize_portfolio(tickers=["AAPL", "MSFT", "NVDA"], years=3)

print(weights)                  # {'AAPL': 0.31, ...}
print(perf["sharpe_ratio"])     # 夏普 / Sortino / Calmar / VaR / CVaR / 回撤 / 集中度
```

风险指标涵盖 Sharpe / Sortino / Calmar / VaR / CVaR / 最大回撤 / 集中度（HHI、有效持仓数、前5大权重）。

---

## 了解更多

- skill 用法与触发：[`SKILL.md`](SKILL.md)
- 进阶文档（行业约束、交易成本、回测等）：[`references/`](references/)

## License

[MIT](LICENSE)
