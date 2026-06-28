"""核心功能模块 - Core Module.

对外的主入口 :class:`PortfolioOptimizer`，把「取数 -> 优化 -> 指标」串成一条龙，
支持美股 / A股 / 港股，数据源自动回退（见 :mod:`portfolio_engine.data`）。
"""

import datetime
import logging
from typing import Any, Dict, Iterable, Optional, Tuple

import pandas as pd

from .constraints import (
    ConstrainedOptimizer,
    SectorConstraint,
    TransactionCost,
    calculate_portfolio_concentration,
)
from .data import DataFetcher, get_default_tickers, load_prices_csv
from .markets import Market
from .optimizer import OptimizationStrategy, PortfolioOptimizerFactory
from .utils import format_performance_output, validate_price_data

logger = logging.getLogger(__name__)

_STRATEGY_MAP = {
    "max_sharpe": OptimizationStrategy.MAX_SHARPE,
    "min_variance": OptimizationStrategy.MIN_VARIANCE,
    "risk_parity": OptimizationStrategy.RISK_PARITY,
    "max_diversification": OptimizationStrategy.MAX_DIVERSIFICATION,
    "equal_weight": OptimizationStrategy.EQUAL_WEIGHT,
}


def _default_date_range(years: Optional[int], start: Optional[str], end: Optional[str]) -> Tuple[str, str]:
    """根据 years / start / end 推断日期范围，缺省回溯 3 年。"""
    if years is not None and (start or end):
        raise ValueError("years 参数与 start_date/end_date 不能同时使用")
    today = datetime.date.today()
    if years is not None:
        return (today - datetime.timedelta(days=years * 365)).isoformat(), today.isoformat()
    if start and end:
        return start, end
    # 默认回溯 3 年
    return (today - datetime.timedelta(days=3 * 365)).isoformat(), today.isoformat()


# ----------------------------------------------------------------- 向后兼容接口
def compute_max_sharpe(
    prices: pd.DataFrame, rf: float = 0.02, max_weight: float = 1.0
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """对给定价格表做最大夏普优化（薄封装，便于脚本直接调用）。"""
    from .optimizer import MaxSharpeOptimizer

    validate_price_data(prices)
    weights, performance = MaxSharpeOptimizer(risk_free_rate=rf, max_weight=max_weight).optimize(prices)
    return weights, format_performance_output(weights, performance)


def fetch_prices(
    tickers: Iterable[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    adjust: str = "qfq",
    market: Optional[str] = None,
) -> pd.DataFrame:
    """获取多只标的的收盘价表（多源自动回退）。"""
    mkt = Market[market.upper()] if market else None
    return DataFetcher(source=source, adjust=adjust).fetch_prices(tickers, start_date, end_date, market=mkt)


class PortfolioOptimizer:
    """投资组合优化器主类（美股 / A股 / 港股通用）。"""

    def __init__(
        self,
        risk_free_rate: float = 0.02,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
        strategy: str = "max_sharpe",
        market: Optional[str] = None,
        source: str = "auto",
        adjust: str = "qfq",
    ):
        """
        Args:
            risk_free_rate: 无风险利率（年化）。
            max_weight: 单一资产最大权重上限。
            min_weight: 单一资产最小权重下限。
            strategy: 优化策略，见 :meth:`available_strategies`。
            market: 市场提示（``"US"`` / ``"CN"`` / ``"HK"``）；``None`` 时按代码自动识别。
            source: 数据源（``"auto"`` / ``"yfinance"`` / ``"akshare"`` / ``"eastmoney"``）。
            adjust: 复权方式（``"qfq"`` / ``"hfq"`` / ``""``）。
        """
        self.risk_free_rate = risk_free_rate
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.strategy_name = strategy
        self.market = market.upper() if market else None
        self.source = source
        self.adjust = adjust

        self.data_fetcher = DataFetcher(source=source, adjust=adjust)
        self.optimizer = PortfolioOptimizerFactory.create(
            strategy=self._get_strategy_enum(strategy),
            risk_free_rate=risk_free_rate,
            max_weight=max_weight,
            min_weight=min_weight,
        )
        self.sector_constraint: Optional[SectorConstraint] = None
        self.transaction_cost: Optional[TransactionCost] = None

    @staticmethod
    def _get_strategy_enum(strategy: str) -> OptimizationStrategy:
        key = strategy.lower()
        if key not in _STRATEGY_MAP:
            raise ValueError(f"不支持的策略: {strategy}. 可用: {list(_STRATEGY_MAP)}")
        return _STRATEGY_MAP[key]

    # ----------------------------------------------------------- 可选高级约束
    def set_sector_constraint(
        self,
        max_sector_weight: float = 0.3,
        min_sectors: int = 3,
        sector_mapping: Optional[Dict[str, str]] = None,
    ) -> None:
        """设置行业约束（主要面向 A 股，见 references/constraints-and-costs.md）。"""
        self.sector_constraint = SectorConstraint(
            max_sector_weight=max_sector_weight, min_sectors=min_sectors
        )
        if sector_mapping:
            for ticker, sector in sector_mapping.items():
                self.sector_constraint.add_sector_mapping(ticker, sector)

    def set_transaction_cost(
        self, commission_rate: float = 0.0003, stamp_duty: float = 0.001, slippage: float = 0.001
    ) -> None:
        """设置交易成本参数。"""
        self.transaction_cost = TransactionCost(
            commission_rate=commission_rate, stamp_duty=stamp_duty, slippage=slippage
        )

    # ----------------------------------------------------------------- 主流程
    def _resolve_prices(
        self,
        tickers: Optional[Iterable[str]],
        start_date: Optional[str],
        end_date: Optional[str],
        years: Optional[int],
        prices: Optional[pd.DataFrame],
        csv: Optional[str],
    ) -> pd.DataFrame:
        """把多种输入方式（现成 df / CSV / 在线抓取）统一成价格表。"""
        if prices is not None:
            return prices
        if csv is not None:
            return load_prices_csv(csv, tickers=tickers)

        if tickers is None:
            tickers = get_default_tickers(self.market or Market.US)
        tickers = list(tickers)
        start, end = _default_date_range(years, start_date, end_date)
        mkt = Market[self.market] if self.market else None
        logger.info("取数 | 策略=%s | 标的=%s%s | %s~%s",
                    self.strategy_name, tickers[:5], "..." if len(tickers) > 5 else "", start, end)
        return self.data_fetcher.fetch_prices(tickers, start, end, market=mkt)

    def optimize_portfolio(
        self,
        tickers: Optional[Iterable[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        years: Optional[int] = None,
        prices: Optional[pd.DataFrame] = None,
        csv: Optional[str] = None,
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """执行完整优化流程，返回 ``(weights, performance)``。

        取数方式（优先级从高到低）：``prices`` 现成表 > ``csv`` 文件 > 在线抓取。
        在线抓取时用 ``tickers`` + (``years`` 或 ``start_date``/``end_date``)。
        """
        prices = self._resolve_prices(tickers, start_date, end_date, years, prices, csv)
        return self._optimize_with_prices(prices)

    def _optimize_with_prices(self, prices: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
        validate_price_data(prices)
        logger.info("成功载入 %d 只标的、%d 个交易日", len(prices.columns), len(prices))

        if self.sector_constraint:
            weights, performance = ConstrainedOptimizer(
                base_optimizer=self.optimizer,
                sector_constraint=self.sector_constraint,
                transaction_cost=self.transaction_cost,
            ).optimize(prices)
        else:
            weights, performance = self.optimizer.optimize(prices)

        performance["concentration_metrics"] = calculate_portfolio_concentration(weights)
        performance["strategy"] = self.strategy_name
        logger.info("优化完成 | 夏普=%.3f", performance.get("sharpe_ratio", 0))
        return weights, performance

    def compare_strategies(
        self,
        tickers: Optional[Iterable[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        years: Optional[int] = None,
        prices: Optional[pd.DataFrame] = None,
        csv: Optional[str] = None,
    ) -> Dict[str, Tuple[Dict[str, float], Dict[str, Any]]]:
        """在同一份价格数据上跑全部策略并返回各自结果，便于横向对比。"""
        prices = self._resolve_prices(tickers, start_date, end_date, years, prices, csv)
        results: Dict[str, Tuple[Dict[str, float], Dict[str, Any]]] = {}
        for strategy in self.available_strategies():
            try:
                opt = PortfolioOptimizer(
                    risk_free_rate=self.risk_free_rate,
                    max_weight=self.max_weight,
                    min_weight=self.min_weight,
                    strategy=strategy,
                )
                results[strategy] = opt.optimize_portfolio(prices=prices)
                logger.info("策略 %s | 夏普=%.3f", strategy, results[strategy][1].get("sharpe_ratio", 0))
            except Exception as exc:  # noqa: BLE001
                logger.error("策略 %s 失败: %s", strategy, exc)
        return results

    def save_results(
        self,
        weights: Dict[str, float],
        performance: Dict[str, Any],
        prices: pd.DataFrame,
        output_dir: str,
        tag: str,
    ) -> Dict[str, str]:
        """把权重 / 价格 / 指标落盘，返回 {类型: 路径}。"""
        import json
        import os

        os.makedirs(output_dir, exist_ok=True)
        paths: Dict[str, str] = {}

        weights_df = (
            pd.DataFrame(list(weights.items()), columns=["ticker", "weight"])
            .query("weight > 0")
            .sort_values("weight", ascending=False)
        )
        paths["weights"] = os.path.join(output_dir, f"weights_{tag}.csv")
        weights_df.to_csv(paths["weights"], index=False)

        paths["prices"] = os.path.join(output_dir, f"prices_{tag}.csv")
        prices.to_csv(paths["prices"])

        serializable = {}
        for k, v in performance.items():
            if isinstance(v, (dict, list, str, int, float, bool, type(None))):
                serializable[k] = v
            elif hasattr(v, "tolist"):
                serializable[k] = v.tolist()
            else:
                serializable[k] = str(v)
        paths["performance"] = os.path.join(output_dir, f"performance_{tag}.json")
        with open(paths["performance"], "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

        for kind, path in paths.items():
            logger.info("%s 已保存: %s", kind, path)
        return paths

    @staticmethod
    def available_strategies() -> list:
        """返回可用策略名列表。"""
        return list(_STRATEGY_MAP)
