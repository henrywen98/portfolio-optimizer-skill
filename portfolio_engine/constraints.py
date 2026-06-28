"""
约束模块 - Constraints Module

提供投资组合约束功能：
- 行业/板块分散约束
- 交易成本计算
- 个股权重约束
- 流动性约束
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np


logger = logging.getLogger(__name__)


class Sector(Enum):
    """A股行业分类（申万一级行业）"""
    AGRICULTURE = "农林牧渔"
    MINING = "采掘"
    CHEMICAL = "化工"
    STEEL = "钢铁"
    NONFERROUS = "有色金属"
    ELECTRONICS = "电子"
    HOME_APPLIANCE = "家用电器"
    FOOD_BEVERAGE = "食品饮料"
    TEXTILE = "纺织服装"
    LIGHT_INDUSTRY = "轻工制造"
    PHARMA = "医药生物"
    UTILITIES = "公用事业"
    TRANSPORT = "交通运输"
    REAL_ESTATE = "房地产"
    COMMERCE = "商业贸易"
    LEISURE = "休闲服务"
    MEDIA = "传媒"
    TELECOM = "通信"
    BANKING = "银行"
    NONBANK_FINANCE = "非银金融"
    AUTO = "汽车"
    MACHINERY = "机械设备"
    DEFENSE = "国防军工"
    COMPUTER = "计算机"
    CONSTRUCTION = "建筑装饰"
    BUILDING_MATERIAL = "建筑材料"
    ELECTRICAL = "电气设备"
    ENVIRONMENTAL = "环保"
    CONGLOMERATE = "综合"
    UNKNOWN = "未知"


# 默认A股行业映射（部分蓝筹股）
DEFAULT_SECTOR_MAPPING = {
    # 食品饮料
    "600519": Sector.FOOD_BEVERAGE,  # 贵州茅台
    "000858": Sector.FOOD_BEVERAGE,  # 五粮液
    "000568": Sector.FOOD_BEVERAGE,  # 泸州老窖
    "600887": Sector.FOOD_BEVERAGE,  # 伊利股份

    # 家用电器
    "000333": Sector.HOME_APPLIANCE,  # 美的集团
    "000651": Sector.HOME_APPLIANCE,  # 格力电器

    # 银行
    "600036": Sector.BANKING,  # 招商银行
    "601318": Sector.NONBANK_FINANCE,  # 中国平安
    "601166": Sector.BANKING,  # 兴业银行
    "600000": Sector.BANKING,  # 浦发银行
    "601398": Sector.BANKING,  # 工商银行

    # 医药生物
    "600276": Sector.PHARMA,  # 恒瑞医药
    "002230": Sector.PHARMA,  # 科大讯飞 (实际是计算机，这里仅为示例)
    "000063": Sector.TELECOM,  # 中兴通讯

    # 电子
    "002594": Sector.AUTO,  # 比亚迪
    "601012": Sector.NONFERROUS,  # 隆基绿能 (光伏龙头)

    # 能源化工
    "600028": Sector.MINING,  # 中国石化
    "601899": Sector.MINING,  # 紫金矿业

    # 汽车
    "601888": Sector.LEISURE,  # 中国中免

    # 建筑建材
    "600031": Sector.MACHINERY,  # 三一重工
    "601668": Sector.CONSTRUCTION,  # 中国建筑

    # 其他
    "600941": Sector.UTILITIES,  # 中国移动
    "600438": Sector.ELECTRICAL,  # 通威股份
    "600585": Sector.PHARMA,  # 海螺水泥 (实际是建材)
    "600019": Sector.STEEL,  # 宝钢股份
    "002352": Sector.ELECTRICAL,  # 顺丰控股 (实际是物流)
    "601766": Sector.MACHINERY,  # 中国中车
    "600030": Sector.NONBANK_FINANCE,  # 中信证券
    "600406": Sector.PHARMA,  # 国电南瑞 (实际是电力设备)
    "002714": Sector.PHARMA,  # 牧原股份 (实际是农业)
}


@dataclass
class TransactionCost:
    """交易成本配置"""
    commission_rate: float = 0.0003  # 佣金率（万分之三，双向收取）
    stamp_duty: float = 0.001  # 印花税（千分之一，仅卖出）
    slippage: float = 0.001  # 滑点（千分之一）
    min_commission: float = 5.0  # 最低佣金（元）

    def calculate_buy_cost(self, value: float) -> float:
        """计算买入成本"""
        commission = max(value * self.commission_rate, self.min_commission)
        slippage_cost = value * self.slippage
        return commission + slippage_cost

    def calculate_sell_cost(self, value: float) -> float:
        """计算卖出成本"""
        commission = max(value * self.commission_rate, self.min_commission)
        stamp_duty_cost = value * self.stamp_duty
        slippage_cost = value * self.slippage
        return commission + stamp_duty_cost + slippage_cost

    def calculate_rebalance_cost(self, buy_value: float, sell_value: float) -> float:
        """计算再平衡总成本"""
        return self.calculate_buy_cost(buy_value) + self.calculate_sell_cost(sell_value)

    def estimate_turnover_cost(self, turnover_rate: float, portfolio_value: float) -> float:
        """
        估算换手成本

        Args:
            turnover_rate: 换手率（0-1）
            portfolio_value: 组合总价值

        Returns:
            估算的交易成本
        """
        # 假设买卖各占换手率的一半
        buy_value = portfolio_value * turnover_rate / 2
        sell_value = portfolio_value * turnover_rate / 2
        return self.calculate_rebalance_cost(buy_value, sell_value)


@dataclass
class SectorConstraint:
    """行业约束配置"""
    sector_mapping: Dict[str, Sector] = field(default_factory=lambda: DEFAULT_SECTOR_MAPPING.copy())
    max_sector_weight: float = 0.3  # 单一行业最大权重
    min_sectors: int = 3  # 最少行业数量
    excluded_sectors: List[Sector] = field(default_factory=list)  # 排除的行业

    def get_sector(self, ticker: str) -> Sector:
        """获取股票所属行业"""
        return self.sector_mapping.get(ticker, Sector.UNKNOWN)

    def add_sector_mapping(self, ticker: str, sector: Sector) -> None:
        """添加行业映射"""
        self.sector_mapping[ticker] = sector

    def validate_weights(self, weights: Dict[str, float]) -> Tuple[bool, List[str]]:
        """
        验证权重是否满足行业约束

        Args:
            weights: 股票权重字典

        Returns:
            (是否满足约束, 违规信息列表)
        """
        violations = []

        # 计算各行业权重
        sector_weights = {}
        for ticker, weight in weights.items():
            sector = self.get_sector(ticker)
            if sector in self.excluded_sectors:
                violations.append(f"包含被排除的行业: {sector.value} ({ticker})")
            sector_weights[sector] = sector_weights.get(sector, 0) + weight

        # 检查单一行业权重
        for sector, weight in sector_weights.items():
            if weight > self.max_sector_weight:
                violations.append(
                    f"行业 {sector.value} 权重 {weight:.2%} 超过限制 {self.max_sector_weight:.2%}"
                )

        # 检查行业数量
        active_sectors = [s for s, w in sector_weights.items() if w > 0.01]
        if len(active_sectors) < self.min_sectors:
            violations.append(
                f"行业数量 {len(active_sectors)} 少于最小要求 {self.min_sectors}"
            )

        return len(violations) == 0, violations

    def get_sector_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """
        计算各行业权重

        Args:
            weights: 股票权重字典

        Returns:
            行业权重字典
        """
        sector_weights = {}
        for ticker, weight in weights.items():
            sector = self.get_sector(ticker)
            sector_name = sector.value
            sector_weights[sector_name] = sector_weights.get(sector_name, 0) + weight

        return sector_weights


class ConstrainedOptimizer:
    """带约束的优化器包装器"""

    def __init__(self, base_optimizer,
                 sector_constraint: Optional[SectorConstraint] = None,
                 transaction_cost: Optional[TransactionCost] = None,
                 current_weights: Optional[Dict[str, float]] = None):
        """
        初始化带约束的优化器

        Args:
            base_optimizer: 基础优化器实例
            sector_constraint: 行业约束配置
            transaction_cost: 交易成本配置
            current_weights: 当前持仓权重（用于计算换手成本）
        """
        self.base_optimizer = base_optimizer
        self.sector_constraint = sector_constraint
        self.transaction_cost = transaction_cost or TransactionCost()
        self.current_weights = current_weights or {}

    def optimize(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        执行带约束的优化

        Args:
            prices: 价格数据

        Returns:
            (权重字典, 性能指标字典)
        """
        # 执行基础优化
        weights, performance = self.base_optimizer.optimize(prices)

        # 应用行业约束
        if self.sector_constraint:
            weights = self._apply_sector_constraint(weights)

        # 计算交易成本影响
        if self.current_weights:
            turnover = self._calculate_turnover(weights)
            cost_impact = self._estimate_cost_impact(turnover)
            performance['estimated_turnover'] = turnover
            performance['estimated_trading_cost'] = cost_impact

        # 添加行业分布信息
        if self.sector_constraint:
            performance['sector_weights'] = self.sector_constraint.get_sector_weights(weights)

        return weights, performance

    def _apply_sector_constraint(self, weights: Dict[str, float]) -> Dict[str, float]:
        """应用行业约束"""
        is_valid, violations = self.sector_constraint.validate_weights(weights)

        if is_valid:
            return weights

        logger.warning(f"原始权重违反行业约束: {violations}")

        # 简单的约束调整：按比例缩减超限行业
        adjusted_weights = weights.copy()

        # 计算行业权重
        sector_weights = {}
        sector_tickers = {}
        for ticker, weight in weights.items():
            sector = self.sector_constraint.get_sector(ticker)
            sector_weights[sector] = sector_weights.get(sector, 0) + weight
            if sector not in sector_tickers:
                sector_tickers[sector] = []
            sector_tickers[sector].append(ticker)

        # 调整超限行业
        for sector, total_weight in sector_weights.items():
            if total_weight > self.sector_constraint.max_sector_weight:
                scale_factor = self.sector_constraint.max_sector_weight / total_weight
                for ticker in sector_tickers.get(sector, []):
                    adjusted_weights[ticker] *= scale_factor

        # 重新归一化
        total = sum(adjusted_weights.values())
        if total > 0:
            adjusted_weights = {k: v / total for k, v in adjusted_weights.items()}

        return adjusted_weights

    def _calculate_turnover(self, new_weights: Dict[str, float]) -> float:
        """计算换手率"""
        all_tickers = set(self.current_weights.keys()) | set(new_weights.keys())
        turnover = 0
        for ticker in all_tickers:
            old = self.current_weights.get(ticker, 0)
            new = new_weights.get(ticker, 0)
            turnover += abs(new - old)
        return turnover / 2  # 单边换手率

    def _estimate_cost_impact(self, turnover: float, portfolio_value: float = 1_000_000) -> float:
        """估算交易成本影响"""
        return self.transaction_cost.estimate_turnover_cost(turnover, portfolio_value)


def calculate_portfolio_concentration(weights: Dict[str, float]) -> Dict[str, float]:
    """
    计算投资组合集中度指标

    Args:
        weights: 权重字典

    Returns:
        集中度指标字典
    """
    weight_array = np.array(list(weights.values()))
    weight_array = weight_array[weight_array > 0]  # 只考虑正权重

    if len(weight_array) == 0:
        return {'hhi': 0, 'effective_n': 0, 'top5_weight': 0}

    # HHI (Herfindahl-Hirschman Index)
    hhi = np.sum(weight_array ** 2)

    # 有效持仓数量 (1/HHI)
    effective_n = 1 / hhi if hhi > 0 else 0

    # 前5大持仓权重
    sorted_weights = np.sort(weight_array)[::-1]
    top5_weight = np.sum(sorted_weights[:5])

    # Gini系数
    n = len(weight_array)
    if n > 1:
        sorted_w = np.sort(weight_array)
        cumsum = np.cumsum(sorted_w)
        gini = (n + 1 - 2 * np.sum(cumsum) / cumsum[-1]) / n
    else:
        gini = 0

    return {
        'hhi': hhi,
        'effective_n': effective_n,
        'top5_weight': top5_weight,
        'gini_coefficient': gini,
        'num_positions': len(weight_array),
    }


def suggest_rebalance(current_weights: Dict[str, float],
                     target_weights: Dict[str, float],
                     threshold: float = 0.03) -> Dict[str, Dict[str, float]]:
    """
    建议再平衡交易

    Args:
        current_weights: 当前权重
        target_weights: 目标权重
        threshold: 偏离阈值，超过此值才建议调整

    Returns:
        建议交易字典
    """
    suggestions = {
        'increase': {},  # 需要增持
        'decrease': {},  # 需要减持
        'no_change': {},  # 无需调整
    }

    all_tickers = set(current_weights.keys()) | set(target_weights.keys())

    for ticker in all_tickers:
        current = current_weights.get(ticker, 0)
        target = target_weights.get(ticker, 0)
        diff = target - current

        if abs(diff) > threshold:
            if diff > 0:
                suggestions['increase'][ticker] = {
                    'current': current,
                    'target': target,
                    'change': diff,
                }
            else:
                suggestions['decrease'][ticker] = {
                    'current': current,
                    'target': target,
                    'change': diff,
                }
        else:
            suggestions['no_change'][ticker] = {
                'current': current,
                'target': target,
                'change': diff,
            }

    return suggestions
