# 更新日志 / CHANGELOG

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [3.0.0] - 2026-06-28

把整个仓库重构成一个 **Claude Code Skill**（`portfolio-optimizer`），并重新支持多市场。

### 新增
- **多市场**：美股 / A股 / 港股，按代码自动识别市场（`portfolio_engine/markets.py`）。
- **多源数据自动回退**（免 API key）：yfinance → akshare → 东方财富直连 → CSV；`auto` 模式按市场选源并逐级回退（`portfolio_engine/data.py`）。
- **CSV 离线数据源**：`load_prices_csv()` / `--csv`，可跨任意市场、不依赖网络。
- `SKILL.md` 作为 skill 入口；`scripts/optimize.py`（优化 + 对比）、`scripts/backtest.py`（回测）两个 CLI。
- `references/` 文档：策略选择、风险指标、数据源、约束与成本、回测。

### 变更
- 引擎包 `maxsharpe/` 重命名为 `portfolio_engine/`；分发名 `portfolio-optimizer-skill`。
- CLI 输出支持 `--format json`，便于程序化解析；默认回溯改为 3 年。
- `requires-python` 提升到 `>=3.9`；交易日历（pandas-market-calendars）改为可选依赖，主流程不再依赖。
- 精简掉 Streamlit UI、Dockerfile、双语 README、examples，CI 收敛为离线测试。

### 修复
- **风险平价**：旧的迭代算法在病态/近零相关协方差下会把有效资产权重压成 0；改用凸风险预算（Spinu/Maillard）公式，保证 long-only 且风险贡献相等，并加回归测试。
- 等权基准净值因 `pct_change` 首行 NaN 导致 `cumprod` 全为 NaN（Alpha 算成 NaN）的回测 bug。

## [2.x] - 2025

- 简化为 A股（CN-only）市场；精简 CLI、文档与配置。
- 刷新中文 README 并新增英文 README；补充 CI、示例与架构说明。

## [1.0.0] - 2025

- 初始发布：A股 + 美股，最大夏普优化，CLI，交易日对齐，基础测试。
- 数据源 akshare（A股）/ yfinance（美股），优化基于 PyPortfolioOpt。

---

## 贡献者

- [@henrywen98](https://github.com/henrywen98)

## 致谢

- [PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt)
- [akshare](https://github.com/akfamily/akshare)
- [yfinance](https://github.com/ranaroussi/yfinance)
