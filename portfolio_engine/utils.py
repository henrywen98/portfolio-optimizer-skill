"""
工具函数模块 - Utilities Module

包含各种辅助函数和工具
"""

import logging
from typing import Tuple
import pandas as pd


logger = logging.getLogger(__name__)


def setup_logger(verbose: bool = True) -> None:
    """设置日志记录器"""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_valid_trade_range(start_date: str, end_date: str, exchange: str = "NYSE") -> Tuple[str, str]:
    """
    将输入的日期范围调整到实际的交易日（可选工具，主流程不依赖它）。

    数据源本身只会返回真实交易日，所以这步并非必需；保留它仅供需要严格对齐
    交易日历的场景使用。依赖可选包 ``pandas-market-calendars``。

    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        exchange: 交易所日历代码
            - ``NYSE``: 纽交所 / 纳斯达克 (美股)
            - ``XSHG``: 上海证券交易所 (A股)
            - ``XHKG``: 香港交易所 (港股)

    Returns:
        (start_date, end_date) 调整后的日期范围
    """
    try:
        import pandas_market_calendars as mcal
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "需要安装 pandas-market-calendars：pip install pandas-market-calendars"
        ) from e

    try:
        cal = mcal.get_calendar(exchange)
        schedule = cal.schedule(start_date=start_date, end_date=end_date)
    except Exception as e:
        logger.warning(f"获取交易日历失败: {e}")
        raise

    if schedule.empty:
        raise ValueError(
            f"未找到有效的交易日，请检查时间范围或交易所日历！交易所: {exchange}"
        )

    start = schedule.index[0].strftime("%Y-%m-%d")
    end = schedule.index[-1].strftime("%Y-%m-%d")

    return start, end


def calculate_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """计算收益率"""
    return prices.pct_change().dropna()


def calculate_annual_metrics(returns: pd.DataFrame, trading_days: int = 252) -> dict:
    """
    计算年化指标
    
    Args:
        returns: 收益率DataFrame
        trading_days: 年化交易日数量
        
    Returns:
        包含年化收益率和波动率的字典
    """
    annual_returns = returns.mean() * trading_days
    annual_volatility = returns.std() * (trading_days ** 0.5)
    
    return {
        'annual_returns': annual_returns,
        'annual_volatility': annual_volatility,
    }


def validate_price_data(prices: pd.DataFrame) -> None:
    """验证价格数据的有效性"""
    if prices.empty:
        raise ValueError("价格数据为空")

    if len(prices.columns) < 2:
        raise ValueError("至少需要2只股票才能进行组合优化")

    # 转换为数值类型
    prices[:] = prices.apply(pd.to_numeric, errors='coerce')

    # 检查并处理缺失值
    if prices.isnull().any().any():
        nan_info = prices.isnull().sum()
        logger.warning(
            f"价格数据中存在缺失值，将进行前向填充: {nan_info[nan_info > 0].to_dict()}"
        )
        
        prices.ffill(inplace=True)
        prices.dropna(inplace=True)

        # 清理后再次检查
        if prices.isnull().any().any():
            nan_info = prices.isnull().sum()
            raise ValueError(
                f"价格数据中仍存在缺失值: {nan_info[nan_info > 0].to_dict()}"
            )

    if prices.empty:
        raise ValueError("清理后价格数据为空")
    
    # 检查是否有负数或零
    if (prices <= 0).any().any():
        raise ValueError("价格数据中包含非正数值")
    
    # 检查数据长度
    if len(prices) < 30:
        logger.warning("价格数据长度较短，可能影响优化结果")


def format_performance_output(weights: dict, performance: dict) -> dict:
    """格式化性能输出"""
    return {
        'weights': {k: float(v) for k, v in weights.items()},
        'expected_annual_return': float(performance.get('expected_annual_return', 0)),
        'annual_volatility': float(performance.get('annual_volatility', 0)),
        'sharpe_ratio': float(performance.get('sharpe_ratio', 0)),
    }


def get_exchange_for_market(market: str) -> str:
    """根据市场类型返回 pandas-market-calendars 的交易所日历代码。"""
    return {"US": "NYSE", "CN": "XSHG", "HK": "XHKG"}.get(str(market).upper(), "NYSE")
