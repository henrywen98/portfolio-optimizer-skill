# 滚动再平衡回测（进阶）

## 做什么

在历史价格上做**滚动窗口优化 + 定期再平衡**：从第 `lookback_days` 天起，每隔 `rebalance_frequency` 天用**前 `lookback_days` 天**的数据重新跑一次组合优化，按新权重再平衡，计入交易成本（佣金 / 印花税 / 滑点），最终得到净值曲线、权重历史与一组绩效指标。

- **无前视偏差**：每次优化只用滚动历史窗口（`prices.iloc[current_idx - lookback : current_idx]`），不碰未来数据。
- **建模是简化的**：按收盘价成交、成本为固定比率、不建模停牌/涨跌停/最小买卖单位（A股一手）/分红再投。小于 `min_trade_value`（默认 1000）的调仓被忽略。优化失败时**保持当前持仓**继续。

## CLI 参数

在仓库根目录下运行 `scripts/backtest.py`。

| 参数 | 默认 | 说明 |
|------|------|------|
| `--tickers` | 演示池 | 逗号分隔代码，缺省按 `--market` 取默认池 |
| `--csv` | — | 本地宽表价格（配合 `--tickers` 选列） |
| `--market` | 自动 | `US` / `CN` / `HK`，强制市场 |
| `--source` | `auto` | `auto` / `yfinance` / `akshare` / `eastmoney` |
| `--adjust` | `qfq` | 复权：`qfq` 前复权 / `hfq` 后复权 / `""` 不复权 |
| `--years` | 5 | 回溯年数；与 `--start/--end` 二选一 |
| `--start` / `--end` | — | `YYYY-MM-DD`，显式指定区间 |
| `--strategy` | `max_sharpe` | 单策略（取值见 optimization 文档） |
| `--compare` | off | 对比**全部**策略，忽略 `--strategy` |
| `--lookback` | 252 | 优化窗口天数（≈1年） |
| `--rebalance` | 63 | 再平衡周期天数（≈季度） |
| `--rf` | 0.02 | 无风险利率 |
| `--max-weight` / `--min-weight` | 0.25 / 0.0 | 单标的权重上下限 |
| `--capital` | 1,000,000 | 初始资金 |
| `--commission` | 0.0003 | 佣金率 |
| `--stamp-duty` | 0.001 | 印花税（**仅卖出**收取，A股） |
| `--slippage` | 0.001 | 滑点 |
| `--benchmark` | 等权组合 | 基准代码；缺省用组合内标的的等权净值 |
| `--format` | `table` | `table` / `json` |
| `--output-dir` | — | 保存净值与权重 CSV |
| `--quiet` | off | 静默日志 |

## 数据量要求

`len(prices) ≥ lookback_days + rebalance_frequency`，否则直接报错（默认即需 ≥ 315 个交易日）。回测要留足历史，建议 **`--years 5`**。

## 输出指标（`result.metrics`）

| 类别 | 字段 |
|------|------|
| 收益 | `total_return`、`annual_return`、`benchmark_return`、`benchmark_annual_return`、`alpha` |
| 风险 | `annual_volatility`、`max_drawdown`、`sharpe_ratio`、`information_ratio`、`win_rate` |
| 交易 | `total_trades`、`rebalance_count`、`total_commission`、`total_stamp_duty`、`total_slippage`、`total_trading_cost`、`cost_ratio` |
| 时间 | `backtest_days`、`backtest_years` |

说明：`alpha = annual_return − benchmark_annual_return`；`information_ratio = alpha / 跟踪误差`；`win_rate` 为日收益为正的比例；`cost_ratio = total_trading_cost / initial_capital`。

带 `--output-dir` 时落盘两个文件：

- `portfolio_values.csv` —— 组合净值时间序列
- `weights_history.csv` —— 每次再平衡后的权重历史（权重为空则不写）

## 示例

```bash
# 单策略：美股 5 年，最大夏普，季度再平衡
python scripts/backtest.py --tickers AAPL,MSFT,NVDA,JPM,KO --years 5 \
    --strategy max_sharpe --lookback 252 --rebalance 63

# 多策略对比：A股，JSON 输出
python scripts/backtest.py --tickers 600519,000858,600036,000333 --years 5 \
    --compare --format json
```

## Python API

```python
from portfolio_engine.backtest import Backtester, BacktestConfig, OptimizationStrategy

cfg = BacktestConfig(lookback_days=252, rebalance_frequency=63,
                     strategy=OptimizationStrategy.MAX_SHARPE, initial_capital=1_000_000)
result = Backtester(cfg).run(prices, benchmark_ticker=None)   # result.metrics / .portfolio_values / .weights_history
results = Backtester(cfg).compare_strategies(prices)          # {strategy_name: BacktestResult}
```

---

回测 ≠ 未来收益。滚动窗口虽避免前视偏差，但仍受**过拟合**与**样本期偏差**影响，成本/停牌等为简化建模。结果仅供研究，**非投资建议**。
