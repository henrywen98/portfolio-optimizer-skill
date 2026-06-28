"""Portfolio Engine —— 多市场投资组合优化引擎。

一个免 API key 的投资组合优化工具包，支持 **美股 / A股 / 港股**，数据源自动回退
（yfinance -> akshare -> 东财直连 -> CSV）。

支持多种优化策略:
- 最大夏普比率 (Max Sharpe)
- 最小方差 (Minimum Variance)
- 风险平价 (Risk Parity)
- 最大分散化 (Maximum Diversification)
- 等权重 (Equal Weight)

功能特性:
- 多市场、多数据源自动回退
- 多策略优化与横向对比
- 专业风险指标（Sharpe / Sortino / Calmar / VaR / CVaR / 回撤 / 集中度）
- 行业约束、交易成本、滚动回测（进阶）
"""

__version__ = "3.0.0"
__author__ = "Henry Wen"
__email__ = "henrywen98@users.noreply.github.com"

# 核心优化器
from .optimizer import (
    MaxSharpeOptimizer,
    MinVarianceOptimizer,
    RiskParityOptimizer,
    MaxDiversificationOptimizer,
    EqualWeightOptimizer,
    BaseOptimizer,
    OptimizationStrategy,
    PortfolioOptimizerFactory,
)

# 市场识别与数据获取
from .markets import Market, detect_market, to_yfinance
from .data import DataFetcher, get_default_tickers, load_prices_csv

# 工具函数
from .utils import get_valid_trade_range, calculate_returns, validate_price_data

# 主接口 / 向后兼容
from .core import compute_max_sharpe, fetch_prices, PortfolioOptimizer

# 约束模块
from .constraints import (
    SectorConstraint,
    TransactionCost,
    ConstrainedOptimizer,
    Sector,
    calculate_portfolio_concentration,
    suggest_rebalance,
)

# 回测模块
from .backtest import (
    Backtester,
    BacktestConfig,
    BacktestResult,
    generate_backtest_report,
)

__all__ = [
    # 版本信息
    "__version__",
    "__author__",

    # 核心优化器
    "MaxSharpeOptimizer",
    "MinVarianceOptimizer",
    "RiskParityOptimizer",
    "MaxDiversificationOptimizer",
    "EqualWeightOptimizer",
    "BaseOptimizer",
    "OptimizationStrategy",
    "PortfolioOptimizerFactory",

    # 市场与数据
    "Market",
    "detect_market",
    "to_yfinance",
    "DataFetcher",
    "get_default_tickers",
    "load_prices_csv",

    # 工具
    "get_valid_trade_range",
    "calculate_returns",
    "validate_price_data",

    # 高级接口
    "compute_max_sharpe",
    "fetch_prices",
    "PortfolioOptimizer",

    # 约束
    "SectorConstraint",
    "TransactionCost",
    "ConstrainedOptimizer",
    "Sector",
    "calculate_portfolio_concentration",
    "suggest_rebalance",

    # 回测
    "Backtester",
    "BacktestConfig",
    "BacktestResult",
    "generate_backtest_report",
]
