# 投资组合优化 Skill

> 一个**免 API key、多市场**的投资组合优化器，以 [Claude Code](https://claude.com/claude-code) **skill** 形式运行 —— 把一组标的（**美股 / A股 / 港股**）配成一份最优权重，并给出完整风险报告。免费数据、零配置。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-d97757.svg)
![No API key](https://img.shields.io/badge/data-免%20API%20key-brightgreen.svg)

[English](README.md) · **简体中文**

> ⚠️ 仅供**教育 / 研究**用途，不构成任何投资建议。

---

## 这是什么

本仓库本身就是一个 Claude Code skill，入口是 [`SKILL.md`](SKILL.md)。装好后用**自然语言**触发，Claude 读取意图、调用引擎、把结果讲清楚：

- “帮我把 AAPL,MSFT,NVDA 配个最大夏普权重”
- “这几只 A股 600519,000858,600036 做个最小方差配置，单只不超过 30%”
- “对比一下这几个标的的几种配置策略，哪个夏普最高”

不用记命令、不用接数据、不用任何交易所 API key —— 配苹果和配茅台是同一套流程。

## 为什么需要它

让通用大模型“写段 PyPortfolioOpt 代码”，你只拿到**数学**，一到要**真实价格**就卡壳：免费美股数据在云 IP 上会被限流；A股 / 港股要做交易所前缀 / `secid` 解析，很容易写错；每个临时脚本都在重造回退逻辑。这个 skill 补的正是“难复现”的那一块：

| | 本 skill | 让 Claude 现写代码 | 常见 GitHub 优化器 |
|---|:---:|:---:|:---:|
| 以 Claude Code skill 运行（自然语言） | ✅ | — | — |
| **美股 + A股 + 港股**，自动识别市场 | ✅ | ⚠️ 自己接 | 多为单市场 |
| **免 API key**，多源自动回退 | ✅ | ❌ 卡在数据 | 看情况 |
| 5 种策略 + 横向对比 | ✅ | ⚠️ 部分 | 多为 1–2 种 |
| 完整风险报告（夏普/Sortino/Calmar/VaR/CVaR/回撤/集中度） | ✅ | ⚠️ 部分 | 看情况 |
| 计入交易成本的滚动再平衡回测 | ✅ | ❌ | 偶有 |
| 离线 CSV 模式（任意市场、不联网） | ✅ | ❌ | 少见 |

数据层是真正的护城河：`auto` 模式按市场选源并逐级回退 —— **yfinance → akshare → 东方财富直连 → 本地 CSV**，全程免 key。

## 安装

标准 Claude Code skill，放进 skills 目录即可：

```bash
git clone https://github.com/henrywen98/portfolio-optimizer-skill \
  ~/.claude/skills/portfolio-optimizer
cd ~/.claude/skills/portfolio-optimizer
pip install -r requirements.txt
```

重启 Claude Code，直接让它优化组合即可（按意图触发）。也可以完全不经过 Claude，直接跑下面的 CLI。

## 快速开始（直接用 CLI）

```bash
# 美股，最大夏普
python scripts/optimize.py --tickers AAPL,MSFT,NVDA,JPM,KO --strategy max_sharpe --years 3

# A股，最小方差，单只不超过 30%
python scripts/optimize.py --tickers 600519,000858,600036 --strategy min_variance --max-weight 0.3

# 横向对比全部策略（输出 JSON）
python scripts/optimize.py --tickers AAPL,MSFT,GOOGL,AMZN,META --compare --format json

# 离线：用本地 CSV（任意市场）
python scripts/optimize.py --csv prices.csv --strategy risk_parity
```

滚动再平衡回测（进阶）：

```bash
python scripts/backtest.py --tickers AAPL,MSFT,NVDA,JPM,KO --years 5 \
    --strategy max_sharpe --lookback 252 --rebalance 63
```

## 5 种优化策略

| 策略 | `--strategy` | 一句话 |
|---|---|---|
| 最大夏普 | `max_sharpe` | 单位风险下追求最高超额收益（默认） |
| 最小方差 | `min_variance` | 在可行集里把组合波动率压到最低 |
| 风险平价 | `risk_parity` | 让每只标的对组合风险的贡献相等（凸风险预算） |
| 最大分散化 | `max_diversification` | 最大化分散化比率，摊薄集中度 |
| 等权重 | `equal_weight` | 简单均分，作为对照基准 |

## 数据源（免 API key）

`auto` 模式按市场自动选择并回退：

| 市场 | 代码示例 | 源顺序 |
|---|---|---|
| 美股 | `AAPL`、`MSFT` | yfinance → akshare → 东财 |
| A股 | `600519`、`000858` | akshare → 东财 → yfinance |
| 港股 | `00700`、`09988` | akshare → 东财 → yfinance |
| 任意（离线） | `--csv prices.csv` | 本地 CSV，不联网 |

## Python API

```python
from portfolio_engine import PortfolioOptimizer

opt = PortfolioOptimizer(strategy="max_sharpe", max_weight=0.3)
weights, perf = opt.optimize_portfolio(tickers=["AAPL", "MSFT", "NVDA"], years=3)

print(weights)               # {'AAPL': 0.31, ...}
print(perf["sharpe_ratio"])  # 夏普 / Sortino / Calmar / VaR / CVaR / 回撤 / 集中度
```

## 目录结构

| 路径 | 作用 |
|---|---|
| `SKILL.md` | **skill 入口**：触发条件、用法、给 Claude 的指引 |
| `portfolio_engine/` | 引擎包：优化器、数据获取、市场识别、约束、回测 |
| `scripts/optimize.py` | CLI：单策略优化 + `--compare` 多策略对比 |
| `scripts/backtest.py` | CLI：滚动窗口优化 + 定期再平衡回测 |
| `references/` | 进阶文档（策略 / 指标 / 数据源 / 约束与成本 / 回测） |
| `tests/` | 离线 pytest 测试（不联网） |

## 它是怎么打磨出来的

这个 skill 从一个单市场 A股工具重构而来，并用**评测闭环**做了加固（带 skill 的 Claude vs. 从零开始的基线，跨多组 prompt 打分）。这一步很值：在一组低相关组合上，基线一度**赢过** skill —— 因为旧的迭代式风险平价在病态协方差下会把有效资产的权重压成 0。修复方案是改用凸风险预算（Spinu/Maillard）公式（`minimize ½·wᵀΣw − (1/n)·Σ ln wᵢ`），现在所有资产都保持 long-only 且风险贡献相等，并配了回归测试。一个 skill 只有在“永远不比直接问模型更差”时才值得触发。

策略数学、风险指标定义、多源数据设计、回测建模详见 [`references/`](references/)。

## 路线图

- 更多市场（伦交所 / 东交所），同一套自动回退
- Black-Litterman / 带观点的配置
- 因子暴露约束

欢迎提 issue / PR。

## License

[MIT](LICENSE) · © 2025 Henry Wen

---

如果它帮你省下了又一次手搓数据接口的功夫，点个 ⭐ 能让更多人找到它。
