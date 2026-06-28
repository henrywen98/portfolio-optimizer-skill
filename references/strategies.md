# 如何选优化策略

portfolio-optimizer 提供 5 种策略（`portfolio_engine/optimizer.py`）。用 `scripts/optimize.py --strategy <名字>` 跑单个，用 `--compare` 在同一份数据上横向对比全部。不确定选哪个就先 `--compare`。

## 场景 → 推荐策略

| 你的目标 / 处境 | 推荐策略 | 一句话理由 |
|---|---|---|
| 追求最优风险调整收益（敢押预期） | `max_sharpe` | 直接最大化 Sharpe，但吃预期收益估计 |
| 厌恶风险、只想波动小 | `min_variance` | 只看协方差，不赌收益 |
| 长期持有、怕单一资产暴雷 | `risk_parity` | 风险贡献均摊，最均衡 |
| 想要最大分散化收益 | `max_diversification` | 显式最大化分散化比率 |
| 要一个简单透明的基准 | `equal_weight` | 1/N，常意外地难被打败 |
| 不确定 / 想看全貌 | `--compare` | 一次跑全部，对比指标再决定 |

## 5 种策略

### max_sharpe — 最大夏普
最大化 `(年化收益 − rf) / 年化波动`，用 PyPortfolioOpt `EfficientFrontier.max_sharpe`。预期收益 = 历史日均收益 × 252。

- 优点：理论上最优风险调整收益。
- 缺点：对预期收益估计极敏感，容易集中到少数标的；样本期不同结果差异大。
- 适用：你对预期收益有信心、追求最高 Sharpe。
- 注意：求解失败时**自动回退等权**（1/N）。

### min_variance — 最小方差
最小化组合波动 `EfficientFrontier.min_volatility`，**完全忽略预期收益**。

- 优点：最稳，波动最低。
- 缺点：不追收益，牛市容易跑输。
- 适用：厌恶风险、求稳。
- 注意：求解失败同样回退等权。

### risk_parity — 风险平价
迭代法让每个资产对组合总风险的贡献相等（基于协方差矩阵，不依赖预期收益）。

- 优点：均衡，对单一资产暴雷更稳；不赌收益。
- 缺点：低波动资产权重偏高，可能隐含杠杆偏好。
- 适用：长期持有、追求稳健均衡的常用选择。

### max_diversification — 最大分散化
用 scipy `SLSQP` 最大化**分散化比率 = 加权平均个股波动 / 组合波动**（≥1，越大越分散）。

- 优点：显式追求分散化收益；输出含 `diversification_ratio`。
- 缺点：分散化最优 ≠ 收益最优。
- 适用：把分散化本身当目标。
- 注意：求解失败回退等权。

### equal_weight — 等权
1/N 平均分配，不做任何优化。

- 优点：最简单透明，零估计误差，常意外地难被打败。
- 缺点：不考虑风险与相关性。
- 适用：基准对照、不想被参数左右。

## 权重约束 `--max-weight` / `--min-weight`

CLI 默认 `--max-weight 0.25`、`--min-weight 0.0`（约束 `0 ≤ min ≤ max ≤ 1`，否则报错）。各策略生效方式不同：

| 策略 | 约束如何作用 | 是否硬性保证 |
|---|---|---|
| max_sharpe | 仅当 max<1 或 min>0 时加进 EfficientFrontier 约束 | 是（求解器内强制） |
| min_variance | 同上 | 是 |
| max_diversification | 作为 SLSQP 的 `bounds` | 是 |
| risk_parity | 迭代解出后 `clip` 到 [min,max] 再归一化 | 否（归一化可能把权重推回上限以外） |
| equal_weight | 完全忽略，恒为 1/N | 不适用 |

实务建议：标的少时设 `--max-weight 0.3~0.5` 防过度集中；想强制每只都持有就用 `--min-weight`（注意会挤掉优化空间）。

## 用法示例

```bash
# 单策略 + 集中度约束
python scripts/optimize.py --tickers AAPL,MSFT,GOOGL --strategy min_variance --max-weight 0.3

# 横向对比全部策略
python scripts/optimize.py --tickers 600519,000858,AAPL --compare
```

---
风险提示：所有指标基于历史数据，历史表现不代表未来收益；本工具仅供研究，非投资建议。
