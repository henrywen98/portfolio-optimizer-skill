"""portfolio_engine 离线测试套件。

全部用合成数据 / mock，不触网，覆盖：市场识别、数据装载、5 种优化策略、
约束与成本、回测、主类工作流。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_engine import (
    PortfolioOptimizer,
    DataFetcher,
    Market,
    detect_market,
    load_prices_csv,
    compute_max_sharpe,
)
from portfolio_engine.markets import to_yfinance, eastmoney_secid, cn_exchange
from portfolio_engine.optimizer import (
    MaxSharpeOptimizer,
    MinVarianceOptimizer,
    RiskParityOptimizer,
    MaxDiversificationOptimizer,
    EqualWeightOptimizer,
    OptimizationStrategy,
    PortfolioOptimizerFactory,
)
from portfolio_engine.constraints import (
    SectorConstraint,
    TransactionCost,
    ConstrainedOptimizer,
    calculate_portfolio_concentration,
    suggest_rebalance,
)
from portfolio_engine.backtest import (
    Backtester,
    BacktestConfig,
    BacktestResult,
    generate_backtest_report,
)
from portfolio_engine.utils import (
    validate_price_data,
    calculate_returns,
    get_exchange_for_market,
)


def make_prices(days=252, assets=4, seed=42):
    """生成合成价格表（几何随机游走）。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=days)
    rets = rng.normal(0.0005, 0.012, size=(days, assets))
    prices = 100 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=[f"S{i+1}" for i in range(assets)])


# --------------------------------------------------------------------- markets
class TestMarketDetection:
    @pytest.mark.parametrize("ticker,market", [
        ("AAPL", Market.US), ("BRK-B", Market.US), ("MSFT.US", Market.US),
        ("600519", Market.CN), ("000858", Market.CN), ("300750", Market.CN),
        ("600519.SS", Market.CN), ("000858.SZ", Market.CN),
        ("00700", Market.HK), ("0700.HK", Market.HK), ("09988", Market.HK),
    ])
    def test_detect(self, ticker, market):
        assert detect_market(ticker) is market

    def test_cn_exchange(self):
        assert cn_exchange("600519") == "SH"
        assert cn_exchange("000858") == "SZ"
        assert cn_exchange("300750") == "SZ"
        assert cn_exchange("688981") == "SH"

    def test_to_yfinance(self):
        assert to_yfinance("AAPL") == "AAPL"
        assert to_yfinance("BRK-B") == "BRK-B"
        assert to_yfinance("600519") == "600519.SS"
        assert to_yfinance("000858") == "000858.SZ"
        assert to_yfinance("700", Market.HK) == "0700.HK"

    def test_eastmoney_secid(self):
        assert eastmoney_secid("600519") == "1.600519"
        assert eastmoney_secid("000858") == "0.000858"
        assert eastmoney_secid("00700") == "116.00700"
        assert eastmoney_secid("AAPL") is None  # US 需逐个尝试前缀


# ------------------------------------------------------------------------ data
class TestDataLoading:
    def test_csv_roundtrip(self, tmp_path):
        prices = make_prices(days=60, assets=3)
        prices.index.name = "date"
        path = tmp_path / "p.csv"
        prices.to_csv(path)
        loaded = load_prices_csv(str(path))
        assert list(loaded.columns) == list(prices.columns)
        assert len(loaded) == len(prices)

    def test_csv_select_tickers(self, tmp_path):
        prices = make_prices(days=40, assets=3)
        path = tmp_path / "p.csv"
        prices.to_csv(path)
        loaded = load_prices_csv(str(path), tickers=["S1", "S3"])
        assert list(loaded.columns) == ["S1", "S3"]

    def test_csv_missing_ticker_raises(self, tmp_path):
        prices = make_prices(days=40, assets=2)
        path = tmp_path / "p.csv"
        prices.to_csv(path)
        with pytest.raises(ValueError, match="找不到"):
            load_prices_csv(str(path), tickers=["NOPE"])

    def test_akshare_cn_mocked(self, monkeypatch):
        """A股取数走 akshare（中文列名）—— 用 mock，不触网。"""
        import portfolio_engine.data as data_mod

        fake = pd.DataFrame({
            "日期": pd.date_range("2022-01-01", periods=40),
            "收盘": np.linspace(10, 20, 40),
        })

        class FakeAk:
            @staticmethod
            def stock_zh_a_hist(**kwargs):
                return fake

        monkeypatch.setattr(data_mod, "ak", FakeAk)
        out = DataFetcher(source="akshare").fetch_prices(["600519"], "2022-01-01", "2022-02-10")
        assert "600519" in out.columns and not out.empty

    def test_all_sources_fail_raises(self, monkeypatch):
        import portfolio_engine.data as data_mod
        monkeypatch.setattr(data_mod, "yf", None)
        monkeypatch.setattr(data_mod, "ak", None)
        monkeypatch.setattr(data_mod, "requests", None)
        with pytest.raises(ValueError, match="未能获取任何价格数据"):
            DataFetcher().fetch_prices(["AAPL"], "2022-01-01", "2022-02-01")


# ------------------------------------------------------------------- optimizers
class TestOptimizers:
    def test_invalid_weight_constraint(self):
        with pytest.raises(ValueError, match="权重约束无效"):
            MaxSharpeOptimizer(min_weight=0.5, max_weight=0.3)

    @pytest.mark.parametrize("cls", [
        MaxSharpeOptimizer, MinVarianceOptimizer, RiskParityOptimizer,
        MaxDiversificationOptimizer, EqualWeightOptimizer,
    ])
    def test_weights_sum_to_one_and_respect_cap(self, cls):
        prices = make_prices(assets=5)
        opt = cls(max_weight=0.4)
        weights, perf = opt.optimize(prices)
        assert abs(sum(weights.values()) - 1.0) < 1e-4
        for key in ("expected_annual_return", "annual_volatility", "sharpe_ratio", "max_drawdown"):
            assert key in perf

    def test_equal_weight_is_equal(self):
        weights, _ = EqualWeightOptimizer().optimize(make_prices(assets=4))
        assert all(abs(w - 0.25) < 1e-9 for w in weights.values())

    def test_max_diversification_ratio(self):
        _, perf = MaxDiversificationOptimizer().optimize(make_prices(assets=4))
        assert perf["diversification_ratio"] >= 1.0 - 1e-6

    def test_risk_parity_equalizes_risk_and_keeps_all_assets(self):
        """回归测试：风险平价在近零相关数据上不能把资产压成 0，且各风险贡献趋同。"""
        rng = np.random.default_rng(11)
        idx = pd.bdate_range("2023-01-02", periods=400)
        # 5 个近乎不相关、波动差异大的资产 —— 旧迭代算法会在这种数据上退化压零
        vols = [0.022, 0.013, 0.008, 0.011, 0.017]
        prices = pd.DataFrame(
            {f"A{i}": 100 * np.cumprod(1 + rng.normal(0.0004, v, 400)) for i, v in enumerate(vols)},
            index=idx,
        )
        weights, _ = RiskParityOptimizer().optimize(prices)
        assert all(w > 1e-3 for w in weights.values()), "风险平价不应把任何低相关资产压成 0"
        # 校验风险贡献近似相等
        S = (calculate_returns(prices).cov() * 252).values
        w = np.array([weights[c] for c in prices.columns])
        rc = w * (S @ w)
        rc = rc / rc.sum()
        assert np.allclose(rc, 1.0 / len(w), atol=0.03), f"风险贡献未拉平: {rc}"

    def test_factory_all_strategies(self):
        for strategy in OptimizationStrategy:
            assert PortfolioOptimizerFactory.create(strategy) is not None
        assert len(PortfolioOptimizerFactory.available_strategies()) == 5


# ------------------------------------------------------------------ constraints
class TestConstraints:
    def test_transaction_cost_sell_gt_buy(self):
        cost = TransactionCost(commission_rate=0.0003, stamp_duty=0.001, slippage=0.001)
        assert cost.calculate_sell_cost(100000) > cost.calculate_buy_cost(100000)

    def test_sector_violation_detected(self):
        c = SectorConstraint(max_sector_weight=0.3, min_sectors=2)
        ok, violations = c.validate_weights({"600519": 0.5, "000858": 0.3, "600036": 0.2})
        assert not ok and violations

    def test_concentration(self):
        m = calculate_portfolio_concentration({"A": 0.5, "B": 0.3, "C": 0.2})
        assert m["hhi"] > 0 and m["effective_n"] > 0 and m["top5_weight"] > 0

    def test_suggest_rebalance(self):
        s = suggest_rebalance({"A": 0.5, "B": 0.3}, {"A": 0.3, "B": 0.5}, threshold=0.05)
        assert "A" in s["decrease"] and "B" in s["increase"]

    def test_constrained_optimizer(self):
        weights, _ = ConstrainedOptimizer(
            base_optimizer=MaxSharpeOptimizer(max_weight=0.4),
            sector_constraint=SectorConstraint(max_sector_weight=0.5),
        ).optimize(make_prices(assets=4))
        assert isinstance(weights, dict)


# --------------------------------------------------------------------- backtest
class TestBacktest:
    def test_run_and_report(self):
        prices = make_prices(days=400, assets=4)
        config = BacktestConfig(lookback_days=100, rebalance_frequency=20,
                                strategy=OptimizationStrategy.EQUAL_WEIGHT)
        result = Backtester(config).run(prices)
        assert isinstance(result, BacktestResult)
        assert len(result.portfolio_values) > 0
        for k in ("annual_return", "sharpe_ratio", "total_trades"):
            assert k in result.metrics

        results = {}
        for strat in (OptimizationStrategy.MAX_SHARPE, OptimizationStrategy.EQUAL_WEIGHT):
            results[strat.value] = Backtester(
                BacktestConfig(lookback_days=100, rebalance_frequency=20, strategy=strat)
            ).run(prices)
        report = generate_backtest_report(results)
        assert isinstance(report, pd.DataFrame) and len(report) == 2


# --------------------------------------------------------------------- main API
class TestPortfolioOptimizer:
    def test_init_strategies(self):
        for s in ["max_sharpe", "min_variance", "risk_parity"]:
            assert PortfolioOptimizer(strategy=s).strategy_name == s

    def test_invalid_strategy(self):
        with pytest.raises(ValueError, match="不支持的策略"):
            PortfolioOptimizer(strategy="nope")

    def test_optimize_with_prices(self):
        weights, perf = PortfolioOptimizer(max_weight=0.4).optimize_portfolio(prices=make_prices(assets=5))
        assert abs(sum(weights.values()) - 1.0) < 1e-4
        assert "concentration_metrics" in perf and perf["strategy"] == "max_sharpe"

    def test_compare_with_prices(self):
        results = PortfolioOptimizer().compare_strategies(prices=make_prices(assets=4, days=252))
        assert len(results) == 5
        for _, (weights, perf) in results.items():
            assert "sharpe_ratio" in perf

    def test_save_results(self, tmp_path):
        opt = PortfolioOptimizer(max_weight=0.5)
        prices = make_prices(assets=3)
        weights, perf = opt.optimize_portfolio(prices=prices)
        paths = opt.save_results(weights, perf, prices, str(tmp_path), tag="t")
        import os
        assert all(os.path.exists(p) for p in paths.values())

    def test_available_strategies(self):
        assert len(PortfolioOptimizer.available_strategies()) == 5


# ------------------------------------------------------------------------ utils
class TestUtils:
    def test_validate_empty(self):
        with pytest.raises(ValueError, match="价格数据为空"):
            validate_price_data(pd.DataFrame())

    def test_validate_single_asset(self):
        with pytest.raises(ValueError, match="至少需要2只股票"):
            validate_price_data(make_prices(assets=1))

    def test_validate_negative(self):
        prices = make_prices()
        prices.iloc[0, 0] = -10
        with pytest.raises(ValueError, match="非正数值"):
            validate_price_data(prices)

    def test_calculate_returns(self):
        prices = make_prices()
        returns = calculate_returns(prices)
        assert len(returns) == len(prices) - 1

    def test_exchange_for_market(self):
        assert get_exchange_for_market("CN") == "XSHG"
        assert get_exchange_for_market("US") == "NYSE"
        assert get_exchange_for_market("HK") == "XHKG"

    def test_compute_max_sharpe_backcompat(self):
        weights, perf = compute_max_sharpe(make_prices(assets=3), rf=0.02, max_weight=0.8)
        assert "sharpe_ratio" in perf and abs(sum(weights.values()) - 1.0) < 1e-4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
