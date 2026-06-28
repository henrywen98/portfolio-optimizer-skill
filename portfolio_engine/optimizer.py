"""
投资组合优化器模块 - Portfolio Optimizer Module

包含多种投资组合优化策略:
- 最大夏普比率 (Max Sharpe)
- 最小方差 (Minimum Variance)
- 风险平价 (Risk Parity)
- 最大分散化 (Maximum Diversification)
- 等权重 (Equal Weight)
"""

import logging
from typing import Dict, Tuple, Any, Optional, List
from enum import Enum
import pandas as pd
import numpy as np

from .utils import validate_price_data, calculate_returns, format_performance_output


logger = logging.getLogger(__name__)


class OptimizationStrategy(Enum):
    """优化策略枚举"""
    MAX_SHARPE = "max_sharpe"
    MIN_VARIANCE = "min_variance"
    RISK_PARITY = "risk_parity"
    MAX_DIVERSIFICATION = "max_diversification"
    EQUAL_WEIGHT = "equal_weight"


class BaseOptimizer:
    """优化器基类"""

    def __init__(self, risk_free_rate: float = 0.02, max_weight: float = 1.0,
                 min_weight: float = 0.0):
        """
        初始化优化器基类

        Args:
            risk_free_rate: 无风险利率 (年化)
            max_weight: 单一资产最大权重限制
            min_weight: 单一资产最小权重限制
        """
        self.risk_free_rate = risk_free_rate
        self.max_weight = max_weight
        self.min_weight = min_weight

        if not 0 <= min_weight <= max_weight <= 1:
            raise ValueError("权重约束无效：需要 0 <= min_weight <= max_weight <= 1")
        if risk_free_rate < 0:
            logger.warning("无风险利率为负值，这在某些经济环境下是可能的")

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """执行投资组合优化 - 子类需实现"""
        raise NotImplementedError("子类需要实现optimize方法")

    def _calculate_performance(self, returns: pd.DataFrame,
                               weights: Dict[str, float]) -> Dict[str, Any]:
        """
        计算投资组合性能指标

        Args:
            returns: 收益率DataFrame
            weights: 权重字典

        Returns:
            性能指标字典
        """
        weight_series = pd.Series(weights)
        aligned_weights = weight_series.reindex(returns.columns, fill_value=0)

        # 计算投资组合收益率
        portfolio_returns = (returns * aligned_weights).sum(axis=1)

        # 计算年化指标
        annual_return = portfolio_returns.mean() * 252
        annual_volatility = portfolio_returns.std() * np.sqrt(252)

        # 计算夏普比率
        if annual_volatility > 0:
            sharpe_ratio = (annual_return - self.risk_free_rate) / annual_volatility
        else:
            sharpe_ratio = 0.0

        # 计算最大回撤
        cumulative_returns = (1 + portfolio_returns).cumprod()
        rolling_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        # 计算VaR (5%和1%分位数)
        var_5 = np.percentile(portfolio_returns, 5)
        var_1 = np.percentile(portfolio_returns, 1)

        # 计算CVaR (条件VaR / Expected Shortfall)
        cvar_5 = portfolio_returns[portfolio_returns <= var_5].mean()

        # 计算Sortino比率 (只考虑下行波动)
        downside_returns = portfolio_returns[portfolio_returns < 0]
        downside_std = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino_ratio = (annual_return - self.risk_free_rate) / downside_std if downside_std > 0 else 0

        # 计算Calmar比率
        calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

        return {
            'expected_annual_return': annual_return,
            'annual_volatility': annual_volatility,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'calmar_ratio': calmar_ratio,
            'max_drawdown': max_drawdown,
            'var_5_percent': var_5,
            'var_1_percent': var_1,
            'cvar_5_percent': cvar_5 if not np.isnan(cvar_5) else var_5,
            'total_return': cumulative_returns.iloc[-1] - 1 if len(cumulative_returns) > 0 else 0,
            'trading_days': len(returns),
        }

    def _get_covariance_matrix(self, returns: pd.DataFrame) -> pd.DataFrame:
        """
        计算稳健的协方差矩阵

        Args:
            returns: 收益率DataFrame

        Returns:
            年化协方差矩阵
        """
        # 使用pandas的cov方法
        S = returns.cov() * 252

        # 验证协方差矩阵
        if pd.DataFrame(S).isnull().any().any():
            raise ValueError("协方差矩阵包含NaN值")

        # 检查协方差矩阵是否为正定
        eigenvals = np.linalg.eigvals(S.values)
        if (eigenvals <= 0).any():
            logger.warning("协方差矩阵不是正定的，进行正则化")
            S = S + np.eye(len(S)) * 1e-6

        return S


class MaxSharpeOptimizer(BaseOptimizer):
    """最大夏普比率投资组合优化器"""

    def __init__(self, risk_free_rate: float = 0.02, max_weight: float = 1.0,
                 min_weight: float = 0.0):
        super().__init__(risk_free_rate, max_weight, min_weight)

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        执行最大夏普比率优化

        Args:
            prices: 价格数据DataFrame

        Returns:
            (weights, performance): 权重字典和性能指标字典
        """
        validate_price_data(prices)
        returns = calculate_returns(prices)

        if returns.empty:
            raise ValueError("无法计算收益率")

        weights, performance = self._compute_max_sharpe(returns)
        return weights, performance

    def _compute_max_sharpe(self, returns: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """计算最大夏普比率投资组合"""
        try:
            from pypfopt.efficient_frontier import EfficientFrontier
        except ImportError as e:
            raise ImportError("需要安装 PyPortfolioOpt：pip install PyPortfolioOpt") from e

        # 验证返回数据
        if returns.isnull().any().any():
            raise ValueError("收益率数据中包含NaN值")

        if (returns == float('inf')).any().any() or (returns == -float('inf')).any().any():
            raise ValueError("收益率数据中包含无穷大值")

        if len(returns) < 30:
            raise ValueError("收益率数据点不足，至少需要30个数据点")

        # 计算年化预期收益率
        daily_returns = returns.mean()
        mu = daily_returns * 252

        if mu.isnull().any():
            logger.warning("预期收益率计算包含NaN值，使用0替换")
            mu = mu.fillna(0)

        # 计算协方差矩阵
        S = self._get_covariance_matrix(returns)

        # 创建有效前沿
        ef = EfficientFrontier(mu, S)

        # 添加权重约束
        if self.max_weight < 1.0 or self.min_weight > 0.0:
            ef.add_constraint(lambda w: w >= self.min_weight)
            ef.add_constraint(lambda w: w <= self.max_weight)

        # 优化最大夏普比率
        try:
            ef.max_sharpe(risk_free_rate=self.risk_free_rate)
            cleaned_weights = ef.clean_weights()
        except Exception as e:
            logger.error(f"优化失败: {e}")
            logger.warning("使用等权重作为后备方案")
            n_assets = len(returns.columns)
            equal_weight = 1.0 / n_assets
            cleaned_weights = {asset: equal_weight for asset in returns.columns}

        performance = self._calculate_performance(returns, cleaned_weights)
        return cleaned_weights, performance


class MinVarianceOptimizer(BaseOptimizer):
    """最小方差投资组合优化器"""

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        执行最小方差优化

        Args:
            prices: 价格数据DataFrame

        Returns:
            (weights, performance): 权重字典和性能指标字典
        """
        validate_price_data(prices)
        returns = calculate_returns(prices)

        if returns.empty:
            raise ValueError("无法计算收益率")

        try:
            from pypfopt.efficient_frontier import EfficientFrontier
        except ImportError as e:
            raise ImportError("需要安装 PyPortfolioOpt：pip install PyPortfolioOpt") from e

        # 计算预期收益率和协方差矩阵
        mu = returns.mean() * 252
        S = self._get_covariance_matrix(returns)

        # 创建有效前沿
        ef = EfficientFrontier(mu, S)

        # 添加权重约束
        if self.max_weight < 1.0 or self.min_weight > 0.0:
            ef.add_constraint(lambda w: w >= self.min_weight)
            ef.add_constraint(lambda w: w <= self.max_weight)

        try:
            ef.min_volatility()
            cleaned_weights = ef.clean_weights()
        except Exception as e:
            logger.error(f"最小方差优化失败: {e}")
            n_assets = len(returns.columns)
            cleaned_weights = {asset: 1.0 / n_assets for asset in returns.columns}

        performance = self._calculate_performance(returns, cleaned_weights)
        return cleaned_weights, performance


class RiskParityOptimizer(BaseOptimizer):
    """风险平价投资组合优化器

    风险平价策略使每个资产对投资组合总风险的贡献相等
    """

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        执行风险平价优化

        Args:
            prices: 价格数据DataFrame

        Returns:
            (weights, performance): 权重字典和性能指标字典
        """
        validate_price_data(prices)
        returns = calculate_returns(prices)

        if returns.empty:
            raise ValueError("无法计算收益率")

        # 计算协方差矩阵
        cov_matrix = self._get_covariance_matrix(returns)

        # 使用迭代方法计算风险平价权重
        weights = self._compute_risk_parity_weights(cov_matrix)

        # 应用权重约束
        weights = self._apply_weight_constraints(weights)

        cleaned_weights = {col: weights[i] for i, col in enumerate(returns.columns)}
        performance = self._calculate_performance(returns, cleaned_weights)

        return cleaned_weights, performance

    def _compute_risk_parity_weights(self, cov_matrix: pd.DataFrame,
                                     max_iterations: int = 1000,
                                     tolerance: float = 1e-8) -> np.ndarray:
        """
        计算风险平价权重

        使用迭代方法使每个资产的风险贡献相等
        """
        n = len(cov_matrix)
        weights = np.ones(n) / n  # 初始等权重

        for _ in range(max_iterations):
            # 计算投资组合方差
            portfolio_var = weights @ cov_matrix.values @ weights

            # 计算边际风险贡献
            marginal_risk = cov_matrix.values @ weights

            # 计算风险贡献
            risk_contrib = weights * marginal_risk / np.sqrt(portfolio_var)

            # 目标风险贡献 (等分)
            target_risk = np.sqrt(portfolio_var) / n

            # 更新权重
            new_weights = weights * target_risk / (risk_contrib + 1e-10)
            new_weights = new_weights / new_weights.sum()  # 归一化

            # 检查收敛
            if np.max(np.abs(new_weights - weights)) < tolerance:
                break

            weights = new_weights

        return weights

    def _apply_weight_constraints(self, weights: np.ndarray) -> np.ndarray:
        """应用权重约束"""
        weights = np.clip(weights, self.min_weight, self.max_weight)
        return weights / weights.sum()  # 重新归一化


class MaxDiversificationOptimizer(BaseOptimizer):
    """最大分散化投资组合优化器

    最大化分散化比率 = 加权平均波动率 / 投资组合波动率
    """

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        执行最大分散化优化

        Args:
            prices: 价格数据DataFrame

        Returns:
            (weights, performance): 权重字典和性能指标字典
        """
        validate_price_data(prices)
        returns = calculate_returns(prices)

        if returns.empty:
            raise ValueError("无法计算收益率")

        # 计算协方差矩阵和波动率
        cov_matrix = self._get_covariance_matrix(returns)
        volatilities = np.sqrt(np.diag(cov_matrix.values))

        # 使用优化求解最大分散化
        weights = self._compute_max_diversification_weights(cov_matrix, volatilities)

        cleaned_weights = {col: weights[i] for i, col in enumerate(returns.columns)}
        performance = self._calculate_performance(returns, cleaned_weights)

        # 添加分散化比率到性能指标
        performance['diversification_ratio'] = self._calculate_diversification_ratio(
            weights, volatilities, cov_matrix.values
        )

        return cleaned_weights, performance

    def _compute_max_diversification_weights(self, cov_matrix: pd.DataFrame,
                                            volatilities: np.ndarray) -> np.ndarray:
        """计算最大分散化权重"""
        try:
            from scipy.optimize import minimize
        except ImportError as e:
            raise ImportError("需要安装 scipy") from e

        n = len(cov_matrix)

        def negative_diversification_ratio(w):
            port_vol = np.sqrt(w @ cov_matrix.values @ w)
            weighted_avg_vol = w @ volatilities
            return -weighted_avg_vol / port_vol if port_vol > 0 else 0

        # 约束条件
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},  # 权重和为1
        ]

        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]

        # 初始权重
        x0 = np.ones(n) / n

        result = minimize(
            negative_diversification_ratio,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )

        if result.success:
            return result.x / result.x.sum()
        else:
            logger.warning("最大分散化优化失败，使用等权重")
            return x0

    def _calculate_diversification_ratio(self, weights: np.ndarray,
                                        volatilities: np.ndarray,
                                        cov_matrix: np.ndarray) -> float:
        """计算分散化比率"""
        port_vol = np.sqrt(weights @ cov_matrix @ weights)
        weighted_avg_vol = weights @ volatilities
        return weighted_avg_vol / port_vol if port_vol > 0 else 1.0


class EqualWeightOptimizer(BaseOptimizer):
    """等权重投资组合优化器"""

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        执行等权重分配

        Args:
            prices: 价格数据DataFrame

        Returns:
            (weights, performance): 权重字典和性能指标字典
        """
        validate_price_data(prices)
        returns = calculate_returns(prices)

        if returns.empty:
            raise ValueError("无法计算收益率")

        n_assets = len(returns.columns)
        equal_weight = 1.0 / n_assets

        cleaned_weights = {col: equal_weight for col in returns.columns}
        performance = self._calculate_performance(returns, cleaned_weights)

        return cleaned_weights, performance


class PortfolioOptimizerFactory:
    """投资组合优化器工厂类"""

    _optimizers = {
        OptimizationStrategy.MAX_SHARPE: MaxSharpeOptimizer,
        OptimizationStrategy.MIN_VARIANCE: MinVarianceOptimizer,
        OptimizationStrategy.RISK_PARITY: RiskParityOptimizer,
        OptimizationStrategy.MAX_DIVERSIFICATION: MaxDiversificationOptimizer,
        OptimizationStrategy.EQUAL_WEIGHT: EqualWeightOptimizer,
    }

    @classmethod
    def create(cls, strategy: OptimizationStrategy,
               risk_free_rate: float = 0.02,
               max_weight: float = 1.0,
               min_weight: float = 0.0) -> BaseOptimizer:
        """
        创建优化器实例

        Args:
            strategy: 优化策略
            risk_free_rate: 无风险利率
            max_weight: 最大权重
            min_weight: 最小权重

        Returns:
            优化器实例
        """
        optimizer_class = cls._optimizers.get(strategy)
        if optimizer_class is None:
            raise ValueError(f"不支持的优化策略: {strategy}")

        return optimizer_class(
            risk_free_rate=risk_free_rate,
            max_weight=max_weight,
            min_weight=min_weight
        )

    @classmethod
    def available_strategies(cls) -> List[str]:
        """返回可用的策略列表"""
        return [s.value for s in OptimizationStrategy]
