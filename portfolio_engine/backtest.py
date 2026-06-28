"""
回测模块 - Backtest Module

提供简单的投资组合回测功能，支持：
- 滚动窗口回测
- 定期再平衡
- 交易成本计算
- 性能对比分析
"""

import logging
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from .optimizer import (
    BaseOptimizer,
    MaxSharpeOptimizer,
    OptimizationStrategy,
    PortfolioOptimizerFactory,
)
from .utils import calculate_returns


logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """回测配置"""
    # 回测窗口设置
    lookback_days: int = 252  # 用于优化的历史数据天数（默认1年）
    rebalance_frequency: int = 63  # 再平衡频率（天数，默认约3个月）

    # 交易成本设置
    commission_rate: float = 0.0003  # 佣金率（万分之三）
    stamp_duty: float = 0.001  # 印花税（仅卖出时收取，千分之一）
    slippage: float = 0.001  # 滑点（千分之一）

    # 优化设置
    strategy: OptimizationStrategy = OptimizationStrategy.MAX_SHARPE
    risk_free_rate: float = 0.02
    max_weight: float = 0.25
    min_weight: float = 0.0

    # 其他设置
    initial_capital: float = 1_000_000  # 初始资金
    min_trade_value: float = 1000  # 最小交易金额


@dataclass
class TradeRecord:
    """交易记录"""
    date: datetime
    ticker: str
    action: str  # 'buy' or 'sell'
    shares: float
    price: float
    value: float
    commission: float
    stamp_duty: float
    slippage_cost: float

    @property
    def total_cost(self) -> float:
        """总交易成本"""
        return self.commission + self.stamp_duty + self.slippage_cost


@dataclass
class BacktestResult:
    """回测结果"""
    # 时间序列数据
    portfolio_values: pd.Series = field(default_factory=pd.Series)
    benchmark_values: pd.Series = field(default_factory=pd.Series)
    weights_history: pd.DataFrame = field(default_factory=pd.DataFrame)

    # 交易记录
    trades: List[TradeRecord] = field(default_factory=list)

    # 性能指标
    metrics: Dict[str, float] = field(default_factory=dict)

    # 再平衡日期
    rebalance_dates: List[datetime] = field(default_factory=list)


class Backtester:
    """投资组合回测器"""

    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        初始化回测器

        Args:
            config: 回测配置
        """
        self.config = config or BacktestConfig()

    def run(self, prices: pd.DataFrame,
            benchmark_ticker: Optional[str] = None) -> BacktestResult:
        """
        运行回测

        Args:
            prices: 价格数据DataFrame（日期为索引，股票代码为列）
            benchmark_ticker: 基准股票代码（如果为None，使用等权组合作为基准）

        Returns:
            回测结果
        """
        if prices.empty:
            raise ValueError("价格数据为空")

        if len(prices) < self.config.lookback_days + self.config.rebalance_frequency:
            raise ValueError(
                f"价格数据不足，需要至少 {self.config.lookback_days + self.config.rebalance_frequency} 天"
            )

        logger.info(f"开始回测，数据范围: {prices.index[0]} 至 {prices.index[-1]}")
        logger.info(f"策略: {self.config.strategy.value}, 再平衡周期: {self.config.rebalance_frequency}天")

        # 初始化结果
        result = BacktestResult()
        portfolio_values = []
        weights_history = []
        trades = []

        # 确定回测开始日期（需要预留lookback窗口）
        start_idx = self.config.lookback_days
        dates = prices.index[start_idx:]

        # 初始化持仓
        current_weights = {}
        current_holdings = {}  # 持股数量
        cash = self.config.initial_capital
        last_rebalance_idx = 0

        # 创建优化器
        optimizer = PortfolioOptimizerFactory.create(
            strategy=self.config.strategy,
            risk_free_rate=self.config.risk_free_rate,
            max_weight=self.config.max_weight,
            min_weight=self.config.min_weight,
        )

        for i, date in enumerate(dates):
            current_idx = start_idx + i
            current_prices = prices.iloc[current_idx]

            # 判断是否需要再平衡
            need_rebalance = (
                i == 0 or  # 第一天
                (i - last_rebalance_idx) >= self.config.rebalance_frequency
            )

            if need_rebalance:
                # 获取历史数据进行优化
                lookback_prices = prices.iloc[current_idx - self.config.lookback_days:current_idx]

                try:
                    new_weights, _ = optimizer.optimize(lookback_prices)

                    # 计算交易并执行
                    trade_records = self._execute_rebalance(
                        date=date,
                        current_holdings=current_holdings,
                        target_weights=new_weights,
                        current_prices=current_prices,
                        cash=cash,
                    )

                    # 更新状态
                    for trade in trade_records:
                        trades.append(trade)
                        if trade.action == 'buy':
                            current_holdings[trade.ticker] = current_holdings.get(trade.ticker, 0) + trade.shares
                            cash -= trade.value + trade.total_cost
                        else:  # sell
                            current_holdings[trade.ticker] = current_holdings.get(trade.ticker, 0) - trade.shares
                            cash += trade.value - trade.total_cost

                    current_weights = new_weights
                    last_rebalance_idx = i
                    result.rebalance_dates.append(date)

                    logger.debug(f"{date}: 再平衡完成，交易数: {len(trade_records)}")

                except Exception as e:
                    logger.warning(f"{date}: 优化失败，保持当前持仓: {e}")

            # 计算当前组合价值
            holdings_value = sum(
                current_holdings.get(ticker, 0) * current_prices.get(ticker, 0)
                for ticker in prices.columns
            )
            total_value = cash + holdings_value
            portfolio_values.append({'date': date, 'value': total_value})

            # 记录权重历史
            if current_weights:
                weight_record = {'date': date}
                weight_record.update(current_weights)
                weights_history.append(weight_record)

        # 整理结果
        result.portfolio_values = pd.DataFrame(portfolio_values).set_index('date')['value']
        result.trades = trades

        if weights_history:
            result.weights_history = pd.DataFrame(weights_history).set_index('date')

        # 计算基准收益
        if benchmark_ticker and benchmark_ticker in prices.columns:
            benchmark_prices = prices[benchmark_ticker].iloc[start_idx:]
            result.benchmark_values = benchmark_prices / benchmark_prices.iloc[0] * self.config.initial_capital
        else:
            # 等权组合作为基准（首行 pct_change 为 NaN，需填 0，否则 cumprod 全成 NaN）
            equal_returns = prices.iloc[start_idx:].pct_change().mean(axis=1).fillna(0)
            result.benchmark_values = (1 + equal_returns).cumprod() * self.config.initial_capital

        # 计算性能指标
        result.metrics = self._calculate_metrics(result)

        return result

    def _execute_rebalance(self, date: datetime, current_holdings: Dict[str, float],
                          target_weights: Dict[str, float], current_prices: pd.Series,
                          cash: float) -> List[TradeRecord]:
        """
        执行再平衡交易

        Args:
            date: 交易日期
            current_holdings: 当前持仓
            target_weights: 目标权重
            current_prices: 当前价格
            cash: 可用现金

        Returns:
            交易记录列表
        """
        trades = []

        # 计算当前组合总价值
        current_value = cash + sum(
            current_holdings.get(ticker, 0) * current_prices.get(ticker, 0)
            for ticker in current_prices.index
        )

        # 计算目标持仓
        target_holdings = {}
        for ticker, weight in target_weights.items():
            if ticker in current_prices.index and current_prices[ticker] > 0:
                target_value = current_value * weight
                target_holdings[ticker] = target_value / current_prices[ticker]

        # 生成交易订单
        all_tickers = set(current_holdings.keys()) | set(target_holdings.keys())

        for ticker in all_tickers:
            current_shares = current_holdings.get(ticker, 0)
            target_shares = target_holdings.get(ticker, 0)
            diff_shares = target_shares - current_shares

            if ticker not in current_prices.index:
                continue

            price = current_prices[ticker]
            trade_value = abs(diff_shares * price)

            # 忽略小额交易
            if trade_value < self.config.min_trade_value:
                continue

            # 计算交易成本
            commission = trade_value * self.config.commission_rate
            stamp_duty = trade_value * self.config.stamp_duty if diff_shares < 0 else 0  # 仅卖出收取
            slippage_cost = trade_value * self.config.slippage

            trade = TradeRecord(
                date=date,
                ticker=ticker,
                action='buy' if diff_shares > 0 else 'sell',
                shares=abs(diff_shares),
                price=price,
                value=trade_value,
                commission=commission,
                stamp_duty=stamp_duty,
                slippage_cost=slippage_cost,
            )
            trades.append(trade)

        return trades

    def _calculate_metrics(self, result: BacktestResult) -> Dict[str, float]:
        """计算回测性能指标"""
        portfolio_values = result.portfolio_values
        benchmark_values = result.benchmark_values

        if len(portfolio_values) < 2:
            return {}

        # 计算收益率
        portfolio_returns = portfolio_values.pct_change().dropna()
        benchmark_returns = benchmark_values.pct_change().dropna()

        # 年化收益率
        total_days = (portfolio_values.index[-1] - portfolio_values.index[0]).days
        years = total_days / 365.25
        total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # 年化波动率
        annual_volatility = portfolio_returns.std() * np.sqrt(252)

        # 夏普比率
        sharpe_ratio = ((annual_return - self.config.risk_free_rate) /
                       annual_volatility) if annual_volatility > 0 else 0

        # 最大回撤
        cumulative = (1 + portfolio_returns).cumprod()
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        # 基准对比
        benchmark_total_return = (benchmark_values.iloc[-1] / benchmark_values.iloc[0]) - 1
        benchmark_annual_return = (1 + benchmark_total_return) ** (1 / years) - 1 if years > 0 else 0
        alpha = annual_return - benchmark_annual_return

        # 交易成本统计
        total_trades = len(result.trades)
        total_commission = sum(t.commission for t in result.trades)
        total_stamp_duty = sum(t.stamp_duty for t in result.trades)
        total_slippage = sum(t.slippage_cost for t in result.trades)
        total_cost = total_commission + total_stamp_duty + total_slippage

        # 胜率（盈利交易比例）
        if len(portfolio_returns) > 0:
            win_rate = (portfolio_returns > 0).mean()
        else:
            win_rate = 0

        # 信息比率（相对基准的夏普）
        excess_returns = portfolio_returns - benchmark_returns
        tracking_error = excess_returns.std() * np.sqrt(252)
        information_ratio = alpha / tracking_error if tracking_error > 0 else 0

        return {
            # 收益指标
            'total_return': total_return,
            'annual_return': annual_return,
            'benchmark_return': benchmark_total_return,
            'benchmark_annual_return': benchmark_annual_return,
            'alpha': alpha,

            # 风险指标
            'annual_volatility': annual_volatility,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'information_ratio': information_ratio,
            'win_rate': win_rate,

            # 交易统计
            'total_trades': total_trades,
            'rebalance_count': len(result.rebalance_dates),
            'total_commission': total_commission,
            'total_stamp_duty': total_stamp_duty,
            'total_slippage': total_slippage,
            'total_trading_cost': total_cost,
            'cost_ratio': total_cost / self.config.initial_capital,

            # 时间信息
            'backtest_days': total_days,
            'backtest_years': years,
        }

    def compare_strategies(self, prices: pd.DataFrame,
                          strategies: Optional[List[OptimizationStrategy]] = None,
                          benchmark_ticker: Optional[str] = None) -> Dict[str, BacktestResult]:
        """
        对比多种策略的回测结果

        Args:
            prices: 价格数据
            strategies: 要对比的策略列表（默认对比所有策略）
            benchmark_ticker: 基准股票代码

        Returns:
            各策略的回测结果字典
        """
        if strategies is None:
            strategies = list(OptimizationStrategy)

        results = {}

        for strategy in strategies:
            logger.info(f"运行策略: {strategy.value}")

            # 创建新配置
            config = BacktestConfig(
                lookback_days=self.config.lookback_days,
                rebalance_frequency=self.config.rebalance_frequency,
                commission_rate=self.config.commission_rate,
                stamp_duty=self.config.stamp_duty,
                slippage=self.config.slippage,
                strategy=strategy,
                risk_free_rate=self.config.risk_free_rate,
                max_weight=self.config.max_weight,
                min_weight=self.config.min_weight,
                initial_capital=self.config.initial_capital,
            )

            backtester = Backtester(config)

            try:
                result = backtester.run(prices, benchmark_ticker)
                results[strategy.value] = result
                logger.info(
                    f"  年化收益: {result.metrics['annual_return']:.2%}, "
                    f"夏普比率: {result.metrics['sharpe_ratio']:.2f}"
                )
            except Exception as e:
                logger.error(f"策略 {strategy.value} 回测失败: {e}")

        return results


def generate_backtest_report(results: Dict[str, BacktestResult]) -> pd.DataFrame:
    """
    生成回测对比报告

    Args:
        results: 各策略的回测结果

    Returns:
        对比报告DataFrame
    """
    report_data = []

    for strategy_name, result in results.items():
        metrics = result.metrics
        report_data.append({
            '策略': strategy_name,
            '总收益': f"{metrics['total_return']:.2%}",
            '年化收益': f"{metrics['annual_return']:.2%}",
            '年化波动率': f"{metrics['annual_volatility']:.2%}",
            '夏普比率': f"{metrics['sharpe_ratio']:.2f}",
            '最大回撤': f"{metrics['max_drawdown']:.2%}",
            'Alpha': f"{metrics['alpha']:.2%}",
            '胜率': f"{metrics['win_rate']:.2%}",
            '交易次数': metrics['total_trades'],
            '总交易成本': f"{metrics['total_trading_cost']:.2f}",
        })

    return pd.DataFrame(report_data)
