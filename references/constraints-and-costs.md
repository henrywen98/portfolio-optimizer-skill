# 行业约束与交易成本（进阶）

> 进阶功能，**主要通过 Python API 使用**。`scripts/optimize.py` CLI 不暴露行业约束；交易成本的实际扣减发生在回测里。
> 源码：`portfolio_engine/constraints.py`、入口封装在 `portfolio_engine/core.py` 的 `PortfolioOptimizer`。

## 入口：PortfolioOptimizer 的两个 setter

```python
from portfolio_engine import PortfolioOptimizer

opt = PortfolioOptimizer(strategy="max_sharpe", market="CN")
opt.set_sector_constraint(max_sector_weight=0.3, min_sectors=3)   # 行业约束
opt.set_transaction_cost(commission_rate=0.0003, slippage=0.001)  # 交易成本估算
weights, perf = opt.optimize_portfolio(tickers=[...], years=3)
```

- 只有调用了 `set_sector_constraint()` 后，`optimize_portfolio` 才会用 `ConstrainedOptimizer` 包一层去施加约束；否则走裸优化器。
- 设了约束后，`perf` 会多出 `sector_weights`、`estimated_turnover`、`estimated_trading_cost`、`concentration_metrics` 等字段。

## SectorConstraint（行业分散）

面向 **A股**，行业用申万一级分类（`Sector` 枚举，如 `食品饮料/银行/医药生物`）。

| 参数 | 默认 | 含义 |
|------|------|------|
| `max_sector_weight` | `0.3` | 单一行业权重上限 |
| `min_sectors` | `3` | 最少覆盖的行业数（权重 >1% 才计入） |
| `excluded_sectors` | `[]` | 完全排除的行业列表 |
| `sector_mapping` | `DEFAULT_SECTOR_MAPPING` | ticker → `Sector` 映射 |

内置 `DEFAULT_SECTOR_MAPPING` 只覆盖**部分 A股蓝筹**（贵州茅台、招商银行、恒瑞医药等约 30 只），未命中的 ticker 归为 `Sector.UNKNOWN`。

**关键方法**
- `validate_weights(weights) -> (bool, [违规信息])`：检查超限行业、行业数不足、是否触碰排除行业。
- `get_sector_weights(weights) -> {行业名: 权重}`：按行业聚合。
- `add_sector_mapping(ticker, sector)`：补充映射，值必须是 `Sector` 枚举成员。

**约束如何生效（近似法，非硬约束求解）**：先跑正常优化拿到权重 → 若违反约束，对**超限行业内的个股按比例缩减**（`scale = max_sector_weight / 行业实际权重`）→ 全组合重新归一化。所以这是事后修正，不保证同时满足所有约束（缩减后归一化可能让别的行业再次微超）。

> 美股 / 港股没有内置映射，必须自带 `sector_mapping`，且值要用 `Sector` 枚举成员（`validate_weights` / `get_sector_weights` 内部会取 `sector.value`，传裸字符串会报错）。

## TransactionCost（交易成本）

| 参数 | 默认 | 说明 |
|------|------|------|
| `commission_rate` | `0.0003` | 佣金，万分之三，**双向**收取 |
| `stamp_duty` | `0.001` | 印花税，千分之一，**仅卖出**（A股特有） |
| `slippage` | `0.001` | 滑点，千分之一 |
| `min_commission` | `5.0` | 单笔最低佣金（元） |

**方法**
- `calculate_buy_cost(value)` = 佣金（含最低 5 元保底）+ 滑点。
- `calculate_sell_cost(value)` = 佣金 + 印花税 + 滑点。
- `estimate_turnover_cost(turnover_rate, portfolio_value)`：按换手率拆成买卖各半估算总成本。

注意区分两条路径：
- **优化路径**：`set_transaction_cost` 配的 `TransactionCost` 只产出一个**估算值**（`perf['estimated_trading_cost']`，默认按 100 万组合估），不改变权重。
- **回测路径**：`scripts/backtest.py` 用 `BacktestConfig` 自己的 `commission_rate / stamp_duty / slippage` 字段，对每一笔再平衡交易**真实扣减**现金，汇总进 `total_trading_cost / cost_ratio`。交易成本对收益的真正影响在这里体现。

## 组合分析工具（纯函数，随时可用）

`calculate_portfolio_concentration(weights)` → 集中度指标：

| key | 含义 |
|-----|------|
| `hhi` | 赫芬达尔指数，Σwᵢ²，越高越集中 |
| `effective_n` | 有效持仓数 = 1/HHI |
| `top5_weight` | 前 5 大持仓权重之和 |
| `gini_coefficient` | 权重基尼系数 |
| `num_positions` | 正权重持仓数 |

`suggest_rebalance(current, target, threshold=0.03)` → 再平衡建议，按偏离阈值分三组：`increase` / `decrease` / `no_change`，每项含 `current / target / change`。

## 示例

A股带自定义行业映射的约束优化：

```python
from portfolio_engine import PortfolioOptimizer
from portfolio_engine.constraints import Sector

opt = PortfolioOptimizer(strategy="max_sharpe", market="CN")
opt.set_sector_constraint(
    max_sector_weight=0.25,
    min_sectors=4,
    sector_mapping={"600519": Sector.FOOD_BEVERAGE, "600036": Sector.BANKING},
)
weights, perf = opt.optimize_portfolio(tickers=["600519", "600036", ...], years=3)
print(perf["sector_weights"])      # 各行业权重
print(perf["concentration_metrics"])
```

再平衡建议：

```python
from portfolio_engine.constraints import suggest_rebalance

plan = suggest_rebalance(
    current_weights={"600519": 0.40, "600036": 0.30, "000333": 0.30},
    target_weights={"600519": 0.30, "600036": 0.35, "000333": 0.35},
    threshold=0.03,
)
print(plan["decrease"])  # {'600519': {'current':0.40,'target':0.30,'change':-0.10}}
```

---

**风险提示**：行业约束是事后按比例缩减的近似修正、交易成本默认值是 A股口径假设，结果仅供研究参考，不构成任何投资建议。
