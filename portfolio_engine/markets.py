"""市场识别与代码规范化 - Market detection & symbol normalization.

一只股票在不同免费数据源里用不同的代码格式，这个模块负责识别市场并互转，
让上层只需要写「人类习惯的代码」（如 ``AAPL``、``600519``、``00700``）。

支持的市场:

- ``US``  美股 (NYSE / NASDAQ / AMEX)，如 ``AAPL``、``MSFT``、``BRK-B``
- ``CN``  A股 (上交所 / 深交所 / 北交所)，如 ``600519``、``000858``、``300750``
- ``HK``  港股，如 ``00700``、``0700``、``09988``

各数据源的代码风格:

- **yfinance**:   US=``AAPL``，CN=``600519.SS`` / ``000858.SZ``，HK=``0700.HK``
- **akshare**:    US=``stock_us_daily(symbol="AAPL")``，
  CN=``stock_zh_a_hist(symbol="600519")``，HK=``stock_hk_hist(symbol="00700")``
"""

from __future__ import annotations

import re
from enum import Enum


class Market(Enum):
    """标的所属市场。"""

    US = "US"
    CN = "CN"
    HK = "HK"


# 用户可显式标注的后缀 -> 市场
_SUFFIX_MARKET = {
    ".SS": Market.CN,  # 上交所 (Yahoo)
    ".SH": Market.CN,  # 上交所 (别名)
    ".SZ": Market.CN,  # 深交所
    ".BJ": Market.CN,  # 北交所
    ".HK": Market.HK,
    ".US": Market.US,
    ".N": Market.US,   # NYSE (部分源)
    ".O": Market.US,   # NASDAQ (部分源)
}


def detect_market(ticker: str) -> Market:
    """从一个代码字符串推断它属于哪个市场。

    规则（按优先级）:

    1. 显式后缀（``.SS`` / ``.SZ`` / ``.HK`` / ``.US`` ...）说了算。
    2. 纯 6 位数字 -> A股 (CN)。
    3. 纯 4-5 位数字 -> 港股 (HK)。
    4. 其余（含字母）-> 美股 (US)。

    无法 100% 准确（数字代码本身有歧义），不确定时让用户用后缀或 ``market=`` 显式指定。
    """
    t = ticker.strip().upper()

    for suffix, market in _SUFFIX_MARKET.items():
        if t.endswith(suffix):
            return market

    core = t.split(".")[0]
    if re.fullmatch(r"\d{6}", core):
        return Market.CN
    if re.fullmatch(r"\d{4,5}", core):
        return Market.HK
    return Market.US


def normalize(ticker: str, market: Market | None = None) -> tuple[str, Market]:
    """把代码拆成「裸代码 + 市场」。

    返回去掉数据源后缀后的核心代码（大写）和判定出的市场。比如
    ``("600519.SS", Market.CN)`` -> ``("600519", Market.CN)``。
    """
    market = market or detect_market(ticker)
    core = ticker.strip().upper().split(".")[0]
    return core, market


def cn_exchange(code: str) -> str:
    """判断 A 股代码属于哪个交易所，返回 ``"SH"`` 或 ``"SZ"``。

    - 6 / 5 / 9 开头 -> 上交所 (主板 / 科创板 688 / B股 900)
    - 其余 (0 / 3 / 2) -> 深交所 (主板 / 创业板 300 / B股 200)
    """
    core = code.split(".")[0]
    return "SH" if core[:1] in {"5", "6", "9"} else "SZ"


def to_yfinance(ticker: str, market: Market | None = None) -> str:
    """转成 yfinance 用的代码。"""
    core, market = normalize(ticker, market)
    if market is Market.US:
        # yfinance 用 ``-`` 表示 class share（BRK.B -> BRK-B）
        return ticker.strip().upper().split(".US")[0].replace(".", "-")
    if market is Market.HK:
        return f"{core.zfill(4)}.HK"
    # CN
    suffix = ".SS" if cn_exchange(core) == "SH" else ".SZ"
    return f"{core}{suffix}"


def eastmoney_secid(ticker: str, market: Market | None = None) -> str | None:
    """转成东方财富 ``secid``（akshare/eastmoney 后端用）。

    US 无法仅凭代码确定交易所前缀（105 NASDAQ / 106 NYSE / 107 AMEX），返回
    ``None`` 让调用方逐一尝试。
    """
    core, market = normalize(ticker, market)
    if market is Market.CN:
        return f"{'1' if cn_exchange(core) == 'SH' else '0'}.{core}"
    if market is Market.HK:
        return f"116.{core.zfill(5)}"
    return None  # US: caller tries 105./106./107.
