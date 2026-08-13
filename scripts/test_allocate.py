"""allocate.py 的单测。

重点验三件事（对应设计文档「测试」一节）：
1. 回撤算得对
2. 超过回撤上限的组合确实被剔除
3. 所有候选都超标时**报错**，而不是硬凑一个假装合规的组合
"""

import numpy as np
import pandas as pd
import pytest

from allocate import (
    AssetSpec,
    InfeasibleConstraint,
    backtest,
    bootstrap_drawdown,
    cvar,
    holding_period_stats,
    max_drawdown,
    solve,
)


# --------------------------------------------------------------- 回撤计算
def test_max_drawdown_simple():
    """峰 120 -> 谷 60，回撤 50%。"""
    s = pd.Series([100.0, 120.0, 60.0, 90.0])
    assert max_drawdown(s) == pytest.approx(-0.5)


def test_max_drawdown_monotonic_up_is_zero():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert max_drawdown(s) == pytest.approx(0.0)


def test_max_drawdown_uses_running_peak_not_global_peak():
    """回撤必须相对**此前的高点**，不是全局最高点。

    序列先从 100 跌到 50（-50%），之后涨到 200 再跌到 150（-25%）。
    正确答案是 -50%；若错误地用全局峰 200 当基准，会算出 -75%。
    """
    s = pd.Series([100.0, 50.0, 200.0, 150.0])
    assert max_drawdown(s) == pytest.approx(-0.5)


# --------------------------------------------------------------- 回测
def _flat_prices(n=500):
    """造一张两资产价格表：safe 缓慢上涨、只有约 2% 的小回撤，risky 中途腰斩。

    safe 特意留一段小回撤——真实世界没有零回撤资产，装置里若给它零回撤，
    「上限严到无解」这条就永远测不出来。
    """
    idx = pd.bdate_range("2015-01-01", periods=n)
    safe_path = np.linspace(100, 130, n)
    dip = slice(n // 4, n // 4 + 20)
    safe_path[dip] = safe_path[dip] * 0.98  # 约 -2% 的小回撤
    safe = pd.Series(safe_path, index=idx)
    risky = pd.Series(
        np.concatenate([
            np.linspace(100, 200, n // 2),      # 先翻倍
            np.linspace(200, 100, n - n // 2),  # 再腰斩 -> 回撤 50%
        ]),
        index=idx,
    )
    return pd.DataFrame({"safe": safe, "risky": risky})


def test_backtest_single_asset_matches_its_own_drawdown():
    """全仓 risky 且不再平衡，组合回撤应等于 risky 自己的回撤（-50%）。"""
    prices = _flat_prices()
    res = backtest(prices, {"safe": 0.0, "risky": 1.0}, rebalance=None)
    assert res["max_drawdown"] == pytest.approx(-0.5, abs=1e-3)


def test_backtest_weights_must_sum_to_one():
    prices = _flat_prices()
    with pytest.raises(ValueError, match="权重和"):
        backtest(prices, {"safe": 0.3, "risky": 0.3}, rebalance=None)


def test_backtest_rejects_unknown_ticker():
    prices = _flat_prices()
    with pytest.raises(ValueError, match="不在价格表"):
        backtest(prices, {"safe": 0.5, "nope": 0.5}, rebalance=None)


# --------------------------------------------------------------- 约束筛选
def _specs():
    return [
        AssetSpec(code="safe", name="安全资产", cls="bond", lo=0.0, hi=1.0),
        AssetSpec(code="risky", name="风险资产", cls="equity", lo=0.0, hi=1.0),
    ]


def test_solve_excludes_portfolios_breaching_the_cap():
    """回撤上限 10% 时，腰斩的 risky 只能占很小权重。"""
    prices = _flat_prices()
    res = solve(prices, _specs(), max_dd=0.10, step=0.05)
    assert res["metrics"]["max_drawdown"] >= -0.10 - 1e-9
    assert res["weights"]["risky"] <= 0.25


def test_solve_returns_the_best_among_compliant_only():
    """返回的组合必须同时满足：回撤达标，且在达标集合里夏普最高。"""
    prices = _flat_prices()
    res = solve(prices, _specs(), max_dd=0.20, step=0.05)
    assert res["metrics"]["max_drawdown"] >= -0.20 - 1e-9
    for cand in res["compliant_sample"]:
        assert cand["max_drawdown"] >= -0.20 - 1e-9


def test_solve_raises_when_nothing_can_meet_the_cap():
    """把上限设到没有任何组合能满足 —— 必须报错，不能返回结果。"""
    prices = _flat_prices()
    with pytest.raises(InfeasibleConstraint) as exc:
        solve(prices, _specs(), max_dd=0.0001, step=0.05)
    # 报错要说清最保守的组合能做到多少，好让用户判断是放宽还是降预期
    assert "最保守" in str(exc.value)
    assert exc.value.best_achievable < 0


def test_solve_respects_per_asset_bounds():
    """单资产上下限必须被遵守。"""
    prices = _flat_prices()
    specs = [
        AssetSpec(code="safe", name="安全", cls="bond", lo=0.0, hi=0.6),
        AssetSpec(code="risky", name="风险", cls="equity", lo=0.4, hi=1.0),
    ]
    res = solve(prices, specs, max_dd=0.60, step=0.05)
    assert res["weights"]["safe"] <= 0.6 + 1e-9
    assert res["weights"]["risky"] >= 0.4 - 1e-9


# --------------------------------------------------------------- 数据窗口校验
def test_solve_reports_subperiod_robustness():
    """结果必须带子区间检验：只在某一段成立的组合要能被看出来。"""
    prices = _flat_prices()
    res = solve(prices, _specs(), max_dd=0.60, step=0.05, n_splits=2)
    assert len(res["robustness"]["splits"]) == 2
    for s in res["robustness"]["splits"]:
        assert "max_drawdown" in s and "cagr" in s and "start" in s


def test_subperiod_breach_is_flagged():
    """全窗口达标、但某个子区间破了上限时，必须标出来。

    risky 的腰斩全部发生在后半段：整段窗口的回撤被前半段的上涨稀释，
    而后半段单独看会破得更厉害。
    """
    prices = _flat_prices()
    res = solve(prices, _specs(), max_dd=0.60, step=0.10, n_splits=2)
    rob = res["robustness"]
    worst = min(s["max_drawdown"] for s in rob["splits"])
    assert rob["worst_subperiod_drawdown"] == pytest.approx(worst)
    assert rob["breached_in_subperiod"] == (worst < -0.60 - 1e-9)


def test_solve_rejects_window_too_short_to_be_meaningful():
    """回测窗口盖不住 A 股历次大跌时必须拒绝出结果（默认要求覆盖 2015-06）。"""
    idx = pd.bdate_range("2021-01-01", periods=300)
    prices = pd.DataFrame(
        {"safe": np.linspace(100, 110, 300), "risky": np.linspace(100, 150, 300)},
        index=idx,
    )
    with pytest.raises(ValueError, match="窗口"):
        solve(prices, _specs(), max_dd=0.20, step=0.05, require_covers="2015-06-30")


# --------------------------------------------------------------- 持有期收益分布
def test_holding_period_stats_shape_and_bounds():
    """持有期分布要给出最差/5分位/中位/最好和亏损概率，且最差 <= 中位 <= 最好。"""
    prices = _flat_prices(n=800)
    st = holding_period_stats(prices, {"safe": 0.5, "risky": 0.5}, horizon_years=1.0)
    assert st is not None
    assert st["worst"] <= st["median"] <= st["best"]
    assert 0.0 <= st["prob_loss"] <= 1.0
    assert st["n_samples"] > 0


def test_holding_period_returns_none_when_history_too_short():
    """历史长度盖不住一个完整持有期时返回 None，而不是硬算一个假数。"""
    prices = _flat_prices(n=100)
    assert holding_period_stats(prices, {"safe": 1.0, "risky": 0.0}, horizon_years=5.0) is None


def test_solve_includes_holding_period_when_horizon_given():
    prices = _flat_prices(n=800)
    res = solve(prices, _specs(), max_dd=0.60, step=0.10, horizon_years=1.0)
    assert res["holding_period"] is not None
    assert res["holding_period"]["horizon_years"] == 1.0
    # 不给期限时不算
    res2 = solve(prices, _specs(), max_dd=0.60, step=0.10)
    assert res2["holding_period"] is None


# --------------------------------------------------------------- 自助法 / CVaR
def test_bootstrap_drawdown_distribution_is_ordered():
    """分位数必须单调：中位 >= p95 >= p99 >= 最差（都是负数）。"""
    prices = _flat_prices(n=600)
    b = bootstrap_drawdown(prices, {"safe": 0.5, "risky": 0.5}, n_paths=200, block_days=20)
    assert b["median"] >= b["p95"] >= b["p99"] >= b["worst"]
    assert b["realized"] <= 0


def test_bootstrap_is_reproducible_with_same_seed():
    prices = _flat_prices(n=600)
    kw = dict(n_paths=100, block_days=20)
    a = bootstrap_drawdown(prices, {"safe": 0.5, "risky": 0.5}, seed=7, **kw)
    b = bootstrap_drawdown(prices, {"safe": 0.5, "risky": 0.5}, seed=7, **kw)
    assert a["p95"] == b["p95"]


def test_bootstrap_rejects_series_too_short_for_blocks():
    prices = _flat_prices(n=60)
    with pytest.raises(ValueError, match="区块自助"):
        bootstrap_drawdown(prices, {"safe": 1.0, "risky": 0.0}, n_paths=10, block_days=40)


def test_cvar_is_worse_than_var():
    """CVaR 是尾部均值，必须不优于 VaR。"""
    prices = _flat_prices(n=600)
    c = cvar(prices, {"safe": 0.5, "risky": 0.5})
    assert c["cvar_daily"] <= c["var_daily"]


# --------------------------------------------------------------- p95 口径
def test_p95_metric_is_never_looser_than_realized():
    """同一个上限下，p95 口径选出的组合，其实现 MDD 必然也达标（超集关系）。"""
    prices = _flat_prices(n=700)
    r = solve(prices, _specs(), max_dd=0.40, step=0.10, risk_metric="p95",
              screen_paths=100, confirm_paths=200)
    assert r["metrics"]["max_drawdown"] >= -0.40 - 1e-9
    assert r["bootstrap"]["p95"] >= -0.40 - 1e-9
    assert r["risk_metric"] == "p95"


def test_p95_metric_yields_no_better_return_than_realized():
    """p95 是更严的约束，收益不可能高于 realized 口径。"""
    prices = _flat_prices(n=700)
    kw = dict(max_dd=0.40, step=0.10)
    a = solve(prices, _specs(), risk_metric="realized", confirm_paths=200, **kw)
    b = solve(prices, _specs(), risk_metric="p95", screen_paths=100, confirm_paths=200, **kw)
    assert b["metrics"]["cagr"] <= a["metrics"]["cagr"] + 1e-9


def _random_prices(n=900, seed=42):
    """带真实随机性的价格表。

    `_flat_prices` 是确定性折线，重采样后 MDD 恒等于那个人为的坑深——自助分布方差
    为零，测不出 p95 与实现值的差异。凡是要检验分布性质的用例都用这个装置。
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    safe = 100 * np.cumprod(1 + rng.normal(0.0002, 0.002, n))
    risky = 100 * np.cumprod(1 + rng.normal(0.0004, 0.018, n))
    return pd.DataFrame({"safe": safe, "risky": risky}, index=idx)


def test_bootstrap_p95_is_deeper_than_realized_on_stochastic_data():
    """真实（随机）数据上，p95 必须显著深于实现值——这正是引入自助的理由。"""
    prices = _random_prices()
    b = bootstrap_drawdown(prices, {"safe": 0.5, "risky": 0.5}, n_paths=1500, block_days=40)
    assert b["p95"] < b["median"]
    assert b["p95"] < b["realized"]


def test_p95_infeasible_message_explains_the_optimism_gap():
    """p95 无解但 realized 有解时，报错要点明这个差异，别让人以为是 bug。"""
    prices = _random_prices()
    realized_ok = solve(prices, _specs(), max_dd=0.06, step=0.10,
                        risk_metric="realized", confirm_paths=300)
    assert realized_ok["metrics"]["max_drawdown"] >= -0.06  # realized 口径下有解
    with pytest.raises(InfeasibleConstraint, match="自助 p95"):
        solve(prices, _specs(), max_dd=0.06, step=0.10, risk_metric="p95",
              screen_paths=300, confirm_paths=300)


def test_reported_p95_never_breaches_the_cap():
    """回归测试：返回结果里报告的 p95 必须真的满足上限。

    早期两阶段实现用 800 条路径粗筛、3000 条复核，只信粗筛的结论，
    结果返回过 p95=-25.4% 却声称满足 25% 上限的组合。
    """
    prices = _random_prices()
    for cap in (0.08, 0.12, 0.20):
        r = solve(prices, _specs(), max_dd=cap, step=0.05, risk_metric="p95",
                  screen_paths=300, confirm_paths=1200)
        assert r["bootstrap"]["p95"] >= -cap - 1e-9, \
            f"上限 {cap:.0%} 但报告 p95 = {r['bootstrap']['p95']:.2%}"
