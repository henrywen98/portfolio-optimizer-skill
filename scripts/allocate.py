#!/usr/bin/env python3
"""在「历史最大回撤 ≤ 上限」这个硬约束下求大类资产权重。

做法是网格搜索 + 真实历史回测，不是解析优化：

- 最大回撤不是权重的凸函数，写不出解析解，本来就得跑历史序列才知道。
- 大类资产只有 6-8 个，网格完全够用，也就不需要 cvxpy 这类重依赖。

最重要的一条行为：**所有候选都超过回撤上限时抛 `InfeasibleConstraint`，
不返回任何组合。** 宁可告诉用户「你的 20% 太严，最保守的组合历史回撤也有 24%」，
也不返回一个假装合规的结果。
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

TRADING_DAYS = 252
# 回测窗口默认必须覆盖到这一天之后，否则 2015 年那波大跌不在样本里，
# 回撤约束就是拿牛市数据算出来的假承诺。
DEFAULT_REQUIRE_COVERS = "2015-06-30"

# 用 Period 的频率别名（M/Q/Y），不是 resample 的 ME/QE/YE —— to_period 只认前者
REBALANCE_RULES = {"monthly": "M", "quarterly": "Q", "yearly": "Y", None: None}


@dataclass(frozen=True)
class AssetSpec:
    """一类资产在组合里的身份和权重区间。"""

    code: str
    name: str
    cls: str          # equity / bond / gold / overseas / sector
    lo: float = 0.0   # 权重下限
    hi: float = 1.0   # 权重上限


class InfeasibleConstraint(Exception):
    """没有任何候选组合能满足回撤上限。

    Attributes:
        best_achievable: 全部候选里最好（最浅）的那个回撤，负数。
        best_weights: 达到该回撤的权重。
    """

    def __init__(self, message: str, best_achievable: float, best_weights: Dict[str, float]):
        super().__init__(message)
        self.best_achievable = best_achievable
        self.best_weights = best_weights


# ------------------------------------------------------------------ 指标
def max_drawdown(nav: pd.Series) -> float:
    """最大回撤，负数（-0.5 表示最深跌过 50%）。

    相对**此前的滚动高点**算，不是全局最高点——用全局峰会把后半段的回撤算大。
    """
    nav = pd.Series(nav).astype(float)
    if nav.empty:
        return 0.0
    running_peak = nav.cummax()
    return float((nav / running_peak - 1.0).min())


# ------------------------------------------------------------------ 回测
class _Prepared:
    """把价格表预处理成「每个再平衡区间的相对价格块」，供网格搜索反复复用。

    网格搜索会对同一张价格表跑上万次回测。若每次都重做 groupby / 除法，绝大部分
    时间花在重复的 DataFrame 运算上（实测 13601 个候选要 60 秒）。这里把与权重
    无关的部分只算一次，之后每个候选只剩矩阵乘法。
    """

    def __init__(self, prices: pd.DataFrame, rebalance: Optional[str]):
        if rebalance not in REBALANCE_RULES:
            raise ValueError(f"不支持的再平衡频率: {rebalance}，可选 {list(REBALANCE_RULES)}")
        px = prices.astype(float).dropna()
        if len(px) < 2:
            raise ValueError("有效价格数据不足 2 行，无法回测")

        self.codes: List[str] = [str(c) for c in px.columns]
        self.index = pd.DatetimeIndex(px.index)
        self.n = len(px)

        freq = REBALANCE_RULES[rebalance]
        values = px.to_numpy(dtype=float)
        if freq is None:
            self.blocks = [values / values[0]]
        else:
            period = self.index.to_period(freq)
            codes_arr = np.asarray(period)
            # 区间边界：相邻元素不同的位置
            bounds = np.flatnonzero(codes_arr[1:] != codes_arr[:-1]) + 1
            self.blocks = [b / b[0] for b in np.split(values, bounds)]

    def nav(self, w: np.ndarray) -> np.ndarray:
        out = np.empty(self.n)
        level = 1.0
        i = 0
        for block in self.blocks:
            seg = level * (block @ w)
            out[i:i + len(seg)] = seg
            level = float(seg[-1])
            i += len(seg)
        return out

    def metrics(self, w: np.ndarray) -> Dict[str, float]:
        return _nav_metrics(self.nav(w), self.n)


def _nav_metrics(nav_arr: np.ndarray, n: int) -> Dict[str, float]:
    peak = np.maximum.accumulate(nav_arr)
    mdd = float((nav_arr / peak - 1.0).min())
    rets = np.diff(nav_arr) / nav_arr[:-1]
    years = n / TRADING_DAYS
    cagr = float(nav_arr[-1] / nav_arr[0]) ** (1 / years) - 1 if years > 0 else 0.0
    vol = float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(rets) > 1 else 0.0
    return {
        "max_drawdown": mdd,
        "cagr": cagr,
        "vol": vol,
        "sharpe": (cagr - 0.02) / vol if vol > 0 else 0.0,
        "total_return": float(nav_arr[-1] - 1.0),
        "days": int(n),
    }


def subperiod_check(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    n_splits: int = 3,
    rebalance: Optional[str] = "quarterly",
) -> Dict:
    """把回测窗口等分成 ``n_splits`` 段，逐段复核这套权重的表现。

    为什么需要这一步：在「合规组合里选历史收益最高」这个目标下，胜出的往往就是
    过去这段窗口里涨得最好的资产——本质是追涨。全窗口的回撤达标，可能只是因为
    某一段的大涨把另一段的下跌稀释了。逐段看能把这种情况暴露出来。

    Returns:
        ``{splits: [...], worst_subperiod_drawdown, breached_in_subperiod}``
        （``breached_in_subperiod`` 由调用方结合自己的上限判定后写入）
    """
    codes = [c for c in prices.columns if c in weights]
    px = pd.DataFrame(prices[codes]).astype(float).dropna()
    bounds = np.linspace(0, len(px), n_splits + 1).astype(int)

    splits: List[Dict] = []
    for i in range(n_splits):
        chunk = px.iloc[bounds[i]:bounds[i + 1]]
        if len(chunk) < 2:
            continue
        prep = _Prepared(chunk, rebalance)
        w = np.array([weights[c] for c in prep.codes], dtype=float)
        m = prep.metrics(w)
        idx = pd.DatetimeIndex(chunk.index)
        splits.append({
            "start": str(pd.Timestamp(idx[0]).date()),  # type: ignore[arg-type]
            "end": str(pd.Timestamp(idx[-1]).date()),  # type: ignore[arg-type]
            "cagr": m["cagr"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
        })

    worst = min((s["max_drawdown"] for s in splits), default=0.0)
    return {"splits": splits, "worst_subperiod_drawdown": worst}


def holding_period_stats(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    horizon_years: float,
    rebalance: Optional[str] = "quarterly",
) -> Optional[Dict]:
    """按用户的实际持有期，统计「买入后持有这么久」的收益分布。

    为什么单靠最大回撤不够：最大回撤衡量的是「中途最难看的时候有多难看」，适合能一直
    拿着、只怕自己扛不住的人。但如果用户三年后要用这笔钱，他真正面对的是**到期那天的
    盈亏**——中途跌多深无所谓，到期是亏是赚才决定他能不能拿回本金。期限越短，两者差别
    越大。

    做法是滚动窗口：以历史上每个交易日为买点，算持有 ``horizon_years`` 后的收益，
    汇总成分布。

    Returns:
        ``{horizon_years, n_samples, worst, p5, median, best, prob_loss}``；
        历史长度不够覆盖一个完整持有期时返回 ``None``。
    """
    codes = [c for c in prices.columns if c in weights]
    px = pd.DataFrame(prices[codes]).astype(float).dropna()
    prep = _Prepared(px, rebalance)
    w = np.array([weights[c] for c in prep.codes], dtype=float)
    nav = prep.nav(w)

    horizon = int(round(horizon_years * TRADING_DAYS))
    if horizon < 1 or len(nav) <= horizon:
        return None

    rets = nav[horizon:] / nav[:-horizon] - 1.0
    return {
        "horizon_years": horizon_years,
        "n_samples": int(len(rets)),
        "worst": float(rets.min()),
        "p5": float(np.percentile(rets, 5)),
        "median": float(np.median(rets)),
        "best": float(rets.max()),
        "prob_loss": float((rets < 0).mean()),
    }


def bootstrap_drawdown(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    n_paths: int = 2000,
    block_days: int = 40,
    rebalance: Optional[str] = "quarterly",
    seed: int = 20260813,
) -> Dict:
    """用平稳区块自助法（stationary block bootstrap）估计最大回撤的**分布**。

    为什么要这一步：历史上实现的那一个 MDD 是**单条路径的单次实现**。它路径依赖、
    非次可加，有效样本量是 1。拿它当硬约束等于把一次实现当成分布——组合看着「历史
    最大回撤 19.2%」，不代表它的 MDD 期望是 19.2%，更不代表 19.2% 是上界。

    做法：对组合日收益按区块重采样（区块长度取几何分布，均值 ``block_days``，以保留
    波动聚集和序列相关），生成等长的合成路径，每条算一个 MDD，汇总成分布。

    区块自助保留短期相关结构但**破坏长期趋势**，所以它给的是「同样的收益分布特征下，
    回撤可能有多深」，不是对未来的预测。极端相关性跃升（危机中相关性冲向 1）它照样
    抓不到，因为重采样是对组合收益整体做的，不重估相关矩阵。

    Returns:
        ``{median, p95, p99, worst, prob_exceed_*}`` —— 均为负数（回撤）。
    """
    codes = [c for c in prices.columns if c in weights]
    prep = _Prepared(pd.DataFrame(prices[codes]), rebalance)
    w = np.array([weights[c] for c in prep.codes], dtype=float)
    nav = prep.nav(w)
    rets = np.diff(nav) / nav[:-1]
    n = len(rets)
    if n < block_days * 3:
        raise ValueError(f"收益序列太短（{n} 天），无法做区块自助")

    rng = np.random.default_rng(seed)
    p = 1.0 / block_days  # 几何分布的续接概率
    mdds = np.empty(n_paths)

    for i in range(n_paths):
        idx = np.empty(n, dtype=np.int64)
        j = 0
        while j < n:
            start = rng.integers(0, n)
            length = min(rng.geometric(p), n - j)
            take = (start + np.arange(length)) % n  # 环绕，保持平稳
            idx[j:j + length] = take
            j += length
        path = np.cumprod(1.0 + rets[idx])
        peak = np.maximum.accumulate(path)
        mdds[i] = float((path / peak - 1.0).min())

    return {
        "n_paths": n_paths,
        "block_days": block_days,
        "median": float(np.percentile(mdds, 50)),
        "p95": float(np.percentile(mdds, 5)),   # 5 分位 = 第 95 百分位的「差」
        "p99": float(np.percentile(mdds, 1)),
        "worst": float(mdds.min()),
        "realized": max_drawdown(pd.Series(nav)),
    }


def cvar(prices: pd.DataFrame, weights: Dict[str, float], alpha: float = 0.05,
         rebalance: Optional[str] = "quarterly") -> Dict[str, float]:
    """日频 VaR 与 CVaR（期望损失）。

    CVaR 是一致性风险度量（次可加），MDD 不是。做组合层面的风险预算时，CVaR 比 MDD
    更适合加总和分解，MDD 的优势只在于它直接对应用户的体感（「我账户最多缩水多少」）。
    两个都报，各管一件事。
    """
    codes = [c for c in prices.columns if c in weights]
    prep = _Prepared(pd.DataFrame(prices[codes]), rebalance)
    w = np.array([weights[c] for c in prep.codes], dtype=float)
    nav = prep.nav(w)
    rets = np.diff(nav) / nav[:-1]
    var = float(np.percentile(rets, alpha * 100))
    tail = rets[rets <= var]
    return {
        "alpha": alpha,
        "var_daily": var,
        "cvar_daily": float(tail.mean()) if len(tail) else var,
        "cvar_annualized": float(tail.mean() * np.sqrt(TRADING_DAYS)) if len(tail) else var,
    }


def backtest(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    rebalance: Optional[str] = "quarterly",
) -> Dict[str, float]:
    """按给定权重跑历史回测，返回净值指标。

    Args:
        prices: 行=交易日，列=标的代码，值=前复权收盘价。
        weights: {代码: 权重}，和必须为 1。
        rebalance: ``monthly`` / ``quarterly`` / ``yearly`` / ``None``（买入后不动）。

    Returns:
        ``{max_drawdown, cagr, vol, sharpe, total_return, days}``
    """
    unknown = [c for c in weights if c not in prices.columns]
    if unknown:
        raise ValueError(f"这些标的不在价格表里: {unknown}")

    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"权重和必须为 1，当前为 {total:.6f}")

    codes = [c for c in prices.columns if c in weights]
    prep = _Prepared(pd.DataFrame(prices[codes]), rebalance)
    w = np.array([weights[c] for c in prep.codes], dtype=float)
    return prep.metrics(w)


# ------------------------------------------------------------------ 候选生成
def _weight_grid(specs: Sequence[AssetSpec], step: float) -> Iterable[Dict[str, float]]:
    """在各资产上下限内枚举权重和为 1 的组合。"""
    n = len(specs)
    if n == 0:
        return
    ticks = int(round(1.0 / step))
    ranges = []
    for s in specs:
        lo_t = int(np.ceil(s.lo * ticks - 1e-9))
        hi_t = int(np.floor(s.hi * ticks + 1e-9))
        ranges.append(range(lo_t, hi_t + 1))

    for combo in itertools.product(*ranges[:-1]):
        used = sum(combo)
        last = ticks - used
        if last in ranges[-1]:
            yield {
                **{specs[i].code: combo[i] / ticks for i in range(n - 1)},
                specs[-1].code: last / ticks,
            }


# ------------------------------------------------------------------ 求解
def solve(
    prices: pd.DataFrame,
    specs: Sequence[AssetSpec],
    max_dd: float,
    step: float = 0.05,
    rebalance: Optional[str] = "quarterly",
    require_covers: Optional[str] = DEFAULT_REQUIRE_COVERS,
    objective: str = "cagr",
    n_splits: int = 3,
    horizon_years: Optional[float] = None,
    risk_metric: str = "p95",
    screen_paths: int = 800,
    confirm_paths: int = 3000,
) -> Dict:
    """求满足回撤上限的最优权重。

    Args:
        prices: 价格宽表。
        specs: 各资产的权重区间。
        max_dd: 最大回撤上限，**正数**（0.20 表示最多回撤 20%）。
        step: 网格步长，0.05 = 5%。
        rebalance: 再平衡频率。
        require_covers: 回测窗口必须覆盖到的日期；``None`` 关闭该校验。
        objective: ``cagr``（默认）或 ``sharpe``。

            默认用 ``cagr`` 是有意的：用户说「我能承受 20% 回撤」，意思是愿意拿这
            20% 去换收益。而在回撤上限下最大化夏普会系统性地**用不满风险预算**
            ——实测 20% 的上限下，夏普最优解只回撤 4.2%、年化 7.2%，等于把用户
            明确授权的风险额度浪费掉了。``sharpe`` 留给想要最优风险收益比、不在乎
            用满预算的场景。

    Returns:
        ``{weights, metrics, n_candidates, n_compliant, frontier, window}``。
        ``frontier`` 是各回撤档位上能拿到的最高收益，用来看放宽/收紧上限的代价。

    Raises:
        ValueError: 窗口太短，或输入不合法。
        InfeasibleConstraint: 没有任何组合满足回撤上限。
    """
    if objective not in ("cagr", "sharpe"):
        raise ValueError(f"objective 只能是 cagr 或 sharpe，收到 {objective}")
    if risk_metric not in ("p95", "realized"):
        raise ValueError(f"risk_metric 只能是 p95 或 realized，收到 {risk_metric}")
    if not 0 < max_dd < 1:
        raise ValueError(f"max_dd 应是 0~1 之间的正数（0.20 表示 20%），收到 {max_dd}")

    index = pd.DatetimeIndex(prices.index)
    win_start, win_end = pd.Timestamp(index[0]), pd.Timestamp(index[-1])

    if require_covers is not None:
        start = win_start
        need = pd.Timestamp(require_covers)
        if start > need:
            raise ValueError(
                f"回测窗口太短：数据从 {start.date()} 开始，盖不住 {need.date()} 之前的下跌。"
                f"只用这段数据算出的回撤约束是假的，拒绝出结果。"
                f"换更早上市的标的，或显式传 require_covers=None 承担风险。"
            )

    codes = [s.code for s in specs]
    prep = _Prepared(pd.DataFrame(prices[codes]), rebalance)
    col_of = {c: i for i, c in enumerate(prep.codes)}

    cap = -abs(max_dd)
    best: Optional[Dict] = None
    best_dd_overall = -1.0
    best_dd_weights: Dict[str, float] = {}
    n_candidates = 0
    n_compliant = 0
    compliant_sample: List[Dict] = []
    # 回撤档位 -> 该档位内能拿到的最高年化，用来展示放宽上限能多换多少收益
    frontier: Dict[int, Dict] = {}

    w_arr = np.zeros(len(prep.codes))
    for weights in _weight_grid(specs, step):
        n_candidates += 1
        w_arr[:] = 0.0
        for code, w in weights.items():
            w_arr[col_of[code]] = w
        metrics = prep.metrics(w_arr)
        dd = metrics["max_drawdown"]

        if dd > best_dd_overall:
            best_dd_overall = dd
            best_dd_weights = dict(weights)

        bucket = int(abs(dd) * 100 // 5) * 5  # 5% 一档
        cur = frontier.get(bucket)
        if cur is None or metrics["cagr"] > cur["cagr"]:
            frontier[bucket] = {**metrics, "weights": dict(weights)}

        if dd < cap:
            continue

        n_compliant += 1
        # 全量留存：第二阶段要按收益降序扫这个池子做自助复核，只留前 50 个会漏解
        compliant_sample.append({**metrics, "weights": dict(weights)})
        if best is None or metrics[objective] > best["metrics"][objective]:
            best = {"weights": dict(weights), "metrics": metrics}

    if n_candidates == 0:
        raise ValueError("权重网格为空：检查各资产的 lo/hi 是否互相矛盾（下限之和 > 1 或上限之和 < 1）")

    if best is None:
        raise InfeasibleConstraint(
            f"没有任何组合能把历史最大回撤控制在 {max_dd:.0%} 以内。"
            f"在 {n_candidates} 个候选里，最保守的组合历史最大回撤是 {best_dd_overall:.1%}。"
            f"要么把上限放宽到 {abs(best_dd_overall):.0%} 以上，要么加入波动更低的资产。",
            best_achievable=best_dd_overall,
            best_weights=best_dd_weights,
        )

    # ---------------------------------------------------------------- 第二阶段
    # 上面按「实现 MDD」筛出的是超集：实现值是单条路径的一次抽样，通常落在自助分布的
    # 中位数附近，因此 |实现| <= |p95|，{p95 达标} ⊆ {实现达标}。所以在这个超集里再
    # 用自助 p95 复核不会漏解。按收益降序逐个复核，命中第一个就停。
    bootstrap_result: Optional[Dict] = None
    if risk_metric == "p95":
        ranked = sorted(compliant_sample, key=lambda x: -x[objective])
        picked = None
        for cand in ranked:
            # 先用少量路径粗筛（便宜），过了再用足量路径复核（准）。
            # **以复核为准**：两个阶段路径数不同，抽样噪声会让粗筛放过实际超标的组合。
            # 早期版本只信粗筛，结果返回过 p95=-25.4% 却声称满足 25% 上限的组合。
            b = bootstrap_drawdown(prices, cand["weights"], n_paths=screen_paths,
                                   block_days=40, rebalance=rebalance)
            if b["p95"] < cap:
                continue
            b = bootstrap_drawdown(prices, cand["weights"], n_paths=confirm_paths,
                                   block_days=40, rebalance=rebalance)
            if b["p95"] >= cap:
                picked = cand
                bootstrap_result = b
                break
        if picked is None:
            deepest = max((c["max_drawdown"] for c in ranked), default=best_dd_overall)
            raise InfeasibleConstraint(
                f"按自助 p95 口径，没有组合能把回撤控制在 {max_dd:.0%} 以内。"
                f"（按实现 MDD 口径有 {n_compliant} 个候选达标——实现值是单条路径的一次抽样，"
                f"系统性乐观。最浅的实现 MDD 是 {deepest:.1%}。）"
                f"要么放宽上限，要么改用 risk_metric='realized' 承担这个乐观偏差。",
                best_achievable=best_dd_overall,
                best_weights=best_dd_weights,
            )
        best = {"weights": picked["weights"],
                "metrics": {k: v for k, v in picked.items() if k != "weights"}}
    else:
        bootstrap_result = bootstrap_drawdown(prices, best["weights"],
                                              n_paths=confirm_paths, block_days=40,
                                              rebalance=rebalance)

    robustness = subperiod_check(prices, best["weights"], n_splits=n_splits, rebalance=rebalance)
    robustness["breached_in_subperiod"] = robustness["worst_subperiod_drawdown"] < cap - 1e-9

    holding = (
        holding_period_stats(prices, best["weights"], horizon_years, rebalance)
        if horizon_years else None
    )

    return {
        **best,
        "robustness": robustness,
        "bootstrap": bootstrap_result,
        "risk_metric": risk_metric,
        "holding_period": holding,
        "objective": objective,
        "n_candidates": n_candidates,
        "n_compliant": n_compliant,
        "compliant_sample": compliant_sample[:50],
        "frontier": [
            {"max_drawdown_bucket": f"{b}~{b + 5}%", **{k: frontier[b][k] for k in ("cagr", "max_drawdown", "sharpe", "weights")}}
            for b in sorted(frontier)
        ],
        "window": {"start": str(win_start.date()), "end": str(win_end.date())},
    }


# ------------------------------------------------------------------ CLI
def _load_prices(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    df.columns = [str(c) for c in df.columns]
    numeric = df.apply(pd.to_numeric, errors="coerce")
    return pd.DataFrame(numeric).dropna()


def main() -> None:
    p = argparse.ArgumentParser(description="回撤约束下的大类资产权重求解")
    p.add_argument("--prices", required=True, help="价格宽表 CSV（fetch_history.py 产出）")
    p.add_argument("--specs", required=True,
                   help="资产定义 JSON：[{code,name,cls,lo,hi}, ...]")
    p.add_argument("--max-dd", type=float, required=True,
                   help="最大回撤上限，正数。0.20 表示最多回撤 20%%")
    p.add_argument("--step", type=float, default=0.05, help="网格步长（默认 0.05）")
    p.add_argument("--rebalance", default="quarterly",
                   choices=["monthly", "quarterly", "yearly", "none"])
    p.add_argument("--risk-metric", choices=["p95", "realized"], default="p95",
                   help="回撤约束按哪个口径。p95=自助分布95分位（默认，诚实）；"
                        "realized=历史实现值（快，但系统性乐观约6个百分点）")
    p.add_argument("--horizon-years", type=float,
                   help="用户的实际持有期（年）。给了就额外输出「持有这么久」的收益分布")
    p.add_argument("--allow-short-window", action="store_true",
                   help="允许回测窗口盖不住 2015（不推荐，回撤约束会失真）")
    args = p.parse_args()

    prices = _load_prices(args.prices)
    with open(args.specs, encoding="utf-8") as f:
        specs = [AssetSpec(**d) for d in json.load(f)]

    missing = [s.code for s in specs if s.code not in prices.columns]
    if missing:
        raise SystemExit(f"价格表里缺这些标的: {missing}")

    try:
        result = solve(
            prices,
            specs,
            max_dd=args.max_dd,
            step=args.step,
            rebalance=None if args.rebalance == "none" else args.rebalance,
            require_covers=None if args.allow_short_window else DEFAULT_REQUIRE_COVERS,
            horizon_years=args.horizon_years,
            risk_metric=args.risk_metric,
        )
    except InfeasibleConstraint as exc:
        print(json.dumps({
            "ok": False,
            "reason": "infeasible",
            "message": str(exc),
            "best_achievable_drawdown": exc.best_achievable,
            "best_weights": exc.best_weights,
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    name_by_code = {s.code: s.name for s in specs}
    print(json.dumps({
        "ok": True,
        "weights": {c: w for c, w in sorted(result["weights"].items(), key=lambda x: -x[1]) if w > 0},
        "names": name_by_code,
        "metrics": result["metrics"],
        "risk_metric": result["risk_metric"],
        "robustness": result["robustness"],
        "bootstrap": result["bootstrap"],
        "holding_period": result["holding_period"],
        "frontier": result["frontier"],
        "window": result["window"],
        "n_candidates": result["n_candidates"],
        "n_compliant": result["n_compliant"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
