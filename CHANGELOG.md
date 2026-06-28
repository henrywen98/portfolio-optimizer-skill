# 更新日志 / CHANGELOG

本文档记录了项目的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [3.0.0] - 2026-06-28

把整个仓库重构成一个 **Claude Code Skill**（`portfolio-optimizer`），并重新支持多市场。

### 新增
- **多市场**：美股 / A股 / 港股，按代码自动识别市场（`portfolio_engine/markets.py`）。
- **多源数据自动回退**（免 API key）：yfinance → akshare → 东方财富直连 → CSV；
  `auto` 模式按市场选源并逐级回退（`portfolio_engine/data.py`）。
- **CSV 离线数据源**：`load_prices_csv()` / `--csv`，可跨任意市场、不依赖网络。
- `SKILL.md` 作为 skill 入口；`scripts/optimize.py`（优化 + 对比）、`scripts/backtest.py`（回测）两个 CLI。
- `references/` 文档：策略选择、风险指标、数据源、约束与成本、回测。

### 变更
- 引擎包 `maxsharpe/` 重命名为 `portfolio_engine/`；分发名 `portfolio-engine` 3.0.0。
- CLI 输出支持 `--format json`，便于程序化解析；默认回溯改为 3 年。
- `requires-python` 提升到 `>=3.9`；交易日历（pandas-market-calendars）改为可选依赖，主流程不再依赖。
- 精简掉 Streamlit UI、Dockerfile、双语 README、examples，CI 收敛为离线测试。

### 修复
- 等权基准净值因 `pct_change` 首行 NaN 导致 `cumprod` 全为 NaN（Alpha/信息比率算成 NaN）的回测 bug。

## [未发布]

### 新增
- 模块化代码结构，提高代码组织性和可维护性
- 新的 `MaxSharpeOptimizer` 类，提供更灵活的优化接口
- `DataFetcher` 类用于统一数据获取
- 完整的示例代码和可视化演示
- 全面的测试套件，包括单元测试和集成测试
- GitHub Actions CI/CD 流水线
- 代码质量检查（black, isort, flake8）
- 详细的贡献指南和项目文档
- Streamlit 前端界面，提供交互式使用体验

### 改进
- 更好的错误处理和日志记录
- 向后兼容的接口设计
- 增强的性能指标计算（包括最大回撤、VaR等）
- 更完善的权重约束验证
- 改进的README文档，包含徽章和详细使用说明
- 投资组合优化前增加价格数据验证
- 详细的缺失值统计和数据质量调试信息
- 移除示例和备份文件，精简代码库

### 修复
- 修复了空数据和无效数据的处理
- 改进了相关性矩阵的数值稳定性
- 修复了权重和为0的边界情况
- 解决了美股数据中缺失值导致优化失败的问题

## [1.0.0] - 2025-01-XX

### 新增
- 初始发布版本
- 支持中国A股和美股市场
- 最大夏普比率投资组合优化
- 自动交易日对齐功能
- 命令行接口
- 基础测试套件

### 支持的功能
- 使用 akshare 获取A股数据
- 使用 yfinance 获取美股数据
- PyPortfolioOpt 投资组合优化
- 权重约束支持
- 多种输出格式（CSV, JSON）
- 性能指标计算

---

## 贡献者

- [@henrywen98](https://github.com/henrywen98) - 项目创始人和主要开发者

## 致谢

感谢以下开源项目的支持：
- [PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt)
- [akshare](https://github.com/akfamily/akshare)  
- [yfinance](https://github.com/ranaroussi/yfinance)
- [pandas-market-calendars](https://github.com/rsheftel/pandas_market_calendars)
# Changelog

## [Unreleased]
- Removed US market support completely (code, tests, scripts, docs)
- Simplified CLI, docs and configs to CN-only
- Dropped yfinance and pandas-datareader dependencies
- Refresh README (CN) and add English README
- Add CI badge; improve docs with examples, Docker, and architecture diagram
