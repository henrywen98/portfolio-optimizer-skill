"""多源行情数据获取 - Multi-source price data fetcher.

支持美股 / A股 / 港股，按市场自动选择数据源并逐级回退，免 API key:

1. **yfinance** —— 美股 / 全球最顺手（直接写 ``AAPL``）；家用 IP 通常很稳，
   数据中心 IP 可能被 Yahoo 限流（HTTP 429）。
2. **akshare** —— A股 / 港股 / 美股都覆盖（底层东方财富 + 新浪），无 key，
   连受限网络也常常能通。
3. **eastmoney（直连）** —— 只依赖 ``requests`` 的兜底实现，三大市场通用，
   在 yfinance 被限流、akshare 没装时仍可工作。
4. **CSV** —— 用户自带价格表，永远兜底，可跨任何市场（见 :func:`load_prices_csv`）。

「auto」模式下美股优先 yfinance，A股 / 港股优先 akshare/eastmoney，失败自动回退。
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

from .markets import (
    Market,
    detect_market,
    eastmoney_secid,
    normalize,
    to_yfinance,
)

logger = logging.getLogger(__name__)

# 可选依赖：缺失时对应数据源自动跳过
try:  # pragma: no cover - optional dependency
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

try:  # pragma: no cover - optional dependency
    import akshare as ak
except ImportError:  # pragma: no cover
    ak = None

try:  # pragma: no cover - optional dependency
    import requests
except ImportError:  # pragma: no cover
    requests = None


_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
}
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 东财复权代码: 0=不复权, 1=前复权, 2=后复权
_EM_FQT = {"": "0", "none": "0", "qfq": "1", "hfq": "2"}


def _to_compact(date_str: str) -> str:
    """``2020-01-01`` -> ``20200101``（兼容已是紧凑格式的输入）。"""
    return str(date_str).replace("-", "")


class DataFetcher:
    """按市场自动选源、逐级回退的价格获取器。

    Args:
        source: ``"auto"``（默认，按市场选源）或强制 ``"yfinance"`` /
            ``"akshare"`` / ``"eastmoney"``。
        adjust: 复权方式，``"qfq"``（前复权，默认）/ ``"hfq"`` / ``""``（不复权）。
    """

    def __init__(self, source: str = "auto", adjust: str = "qfq"):
        self.source = source
        self.adjust = adjust

    # ------------------------------------------------------------------ public
    def fetch_prices(
        self,
        tickers: Iterable[str],
        start_date: str,
        end_date: str,
        market: Optional[Market] = None,
    ) -> pd.DataFrame:
        """抓取多只标的的收盘价并对齐成一张表。

        Returns:
            行=交易日 (DatetimeIndex)，列=输入的原始代码，值=收盘价。
            前向填充后丢弃仍含缺失的行（标的上市时间不一致时的早期空档）。
        """
        series: Dict[str, pd.Series] = {}
        errors: Dict[str, str] = {}

        for ticker in tickers:
            mkt = market or detect_market(ticker)
            try:
                s = self._fetch_one(ticker, mkt, start_date, end_date)
            except Exception as exc:  # noqa: BLE001 - 汇总后统一报告
                s = None
                errors[ticker] = str(exc)
            if s is not None and not s.empty:
                series[ticker] = s
            else:
                errors.setdefault(ticker, "所有数据源均无返回")
                logger.warning("标的 %s 无法获取数据: %s", ticker, errors[ticker])

        if not series:
            raise ValueError(f"未能获取任何价格数据。失败详情: {errors}")
        if errors:
            logger.warning("以下标的被跳过: %s", list(errors))

        df = pd.DataFrame(series).sort_index()
        df = df.apply(pd.to_numeric, errors="coerce")
        df = df.ffill().dropna()
        df.index.name = "date"  # 统一索引名（A股源默认是「日期」）
        if df.empty:
            raise ValueError("价格数据对齐后为空：各标的交易日重叠不足，请检查代码或时间范围。")
        return df

    # ----------------------------------------------------------------- sources
    def _fetch_one(
        self, ticker: str, market: Market, start: str, end: str
    ) -> Optional[pd.Series]:
        last_exc: Optional[Exception] = None
        for source in self._source_order(market):
            try:
                s = source(ticker, market, start, end)
            except Exception as exc:  # noqa: BLE001 - 回退到下一个源
                last_exc = exc
                logger.debug("%s: 源 %s 失败 (%s)，回退下一个", ticker, source.__name__, exc)
                continue
            if s is not None and not s.empty:
                logger.info("%s: 命中 %s（%d 条）", ticker, source.__name__, len(s))
                return s.rename(ticker)
        if last_exc:
            logger.debug("%s: 全部数据源失败，最后错误: %s", ticker, last_exc)
        return None

    def _source_order(
        self, market: Market
    ) -> List[Callable[[str, Market, str, str], Optional[pd.Series]]]:
        explicit = {
            "yfinance": [self._from_yfinance],
            "akshare": [self._from_akshare],
            "eastmoney": [self._from_eastmoney],
        }
        if self.source in explicit:
            return explicit[self.source]
        # auto: 美股优先 yfinance；A股 / 港股优先东财系
        if market is Market.US:
            return [self._from_yfinance, self._from_akshare, self._from_eastmoney]
        return [self._from_akshare, self._from_eastmoney, self._from_yfinance]

    def _from_yfinance(
        self, ticker: str, market: Market, start: str, end: str
    ) -> Optional[pd.Series]:
        if yf is None:
            return None
        symbol = to_yfinance(ticker, market)
        df = yf.download(
            symbol,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):  # 多列时取第一列
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index)
        return close.dropna()

    def _from_akshare(
        self, ticker: str, market: Market, start: str, end: str
    ) -> Optional[pd.Series]:
        if ak is None:
            return None
        core, market = normalize(ticker, market)
        s, e = _to_compact(start), _to_compact(end)

        if market is Market.CN:
            df = ak.stock_zh_a_hist(
                symbol=core, period="daily", start_date=s, end_date=e, adjust=self.adjust
            )
            return _close_from_cn_df(df)
        if market is Market.HK:
            df = ak.stock_hk_hist(
                symbol=core.zfill(5),
                period="daily",
                start_date=s,
                end_date=e,
                adjust=self.adjust,
            )
            return _close_from_cn_df(df)
        # US: 新浪源，整段历史，按日期切片
        df = ak.stock_us_daily(
            symbol=core, adjust=self.adjust if self.adjust in ("qfq", "hfq") else ""
        )
        return _close_from_us_df(df, start, end)

    def _from_eastmoney(
        self, ticker: str, market: Market, start: str, end: str
    ) -> Optional[pd.Series]:
        """只依赖 requests 的东财直连兜底，三大市场通用。"""
        if requests is None:
            return None
        core, market = normalize(ticker, market)
        secids = (
            [f"{p}.{core}" for p in ("105", "106", "107")]  # US: NASDAQ/NYSE/AMEX 逐一试
            if market is Market.US
            else [eastmoney_secid(ticker, market)]
        )
        for secid in secids:
            if not secid:
                continue
            out = self._eastmoney_klines(secid, start, end)
            if out is not None and not out.empty:
                return out
        return None

    def _eastmoney_klines(self, secid: str, start: str, end: str) -> Optional[pd.Series]:
        params = {
            "secid": secid,
            "fields1": "f1",
            "fields2": "f51,f53",  # f51=日期, f53=收盘价
            "klt": "101",  # 日线
            "fqt": _EM_FQT.get(self.adjust, "1"),
            "beg": _to_compact(start),
            "end": _to_compact(end),
        }
        r = requests.get(_EM_KLINE_URL, params=params, headers=_UA, timeout=15)
        data = (r.json() or {}).get("data") or {}
        klines = data.get("klines") or []
        if not klines:
            return None
        dates, closes = [], []
        for row in klines:
            parts = row.split(",")
            dates.append(pd.Timestamp(parts[0]))
            closes.append(float(parts[1]))
        return pd.Series(closes, index=pd.DatetimeIndex(dates))


def _close_from_cn_df(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    """从 akshare A股 / 港股 DataFrame（中文列名）提取收盘价序列。"""
    if df is None or df.empty:
        return None
    date_col = "日期" if "日期" in df.columns else df.columns[0]
    close_col = "收盘" if "收盘" in df.columns else None
    if close_col is None:
        return None
    out = df[[date_col, close_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col])
    return (
        out.set_index(date_col)[close_col]
        .pipe(pd.to_numeric, errors="coerce")
        .sort_index()
        .dropna()
    )


def _close_from_us_df(
    df: Optional[pd.DataFrame], start: str, end: str
) -> Optional[pd.Series]:
    """从 akshare ``stock_us_daily``（英文列名、整段历史）提取并切片收盘价。"""
    if df is None or df.empty:
        return None
    date_col = "date" if "date" in df.columns else df.columns[0]
    close_col = "close" if "close" in df.columns else None
    if close_col is None:
        return None
    out = df[[date_col, close_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col])
    s = (
        out.set_index(date_col)[close_col]
        .pipe(pd.to_numeric, errors="coerce")
        .sort_index()
        .dropna()
    )
    return s.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def load_prices_csv(
    path: str,
    date_col: Optional[str] = None,
    tickers: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """从 CSV 读取价格表（用户自带数据，跨市场通用）。

    期望「宽表」: 第一列是日期，其余每列是一只标的的收盘价（列名=代码）。

    Args:
        path: CSV 路径。
        date_col: 日期列名；缺省取第一列。
        tickers: 只保留这些列（缺省全部）。
    """
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"CSV 为空: {path}")
    date_col = date_col or df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")
    if tickers is not None:
        keep = [t for t in tickers if t in df.columns]
        if not keep:
            raise ValueError(
                f"CSV 中找不到指定标的: {list(tickers)}；可用列: {list(df.columns)}"
            )
        df = df[keep]
    return df.ffill().dropna()


# 默认股票池（演示用，可用 --tickers 覆盖）
DEFAULT_TICKERS_CN = [
    "600519", "000858", "600036", "601318", "000333",
    "600276", "002594", "300750", "601012", "600887",
]
DEFAULT_TICKERS_US = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "JPM", "JNJ", "KO", "XOM",
]
DEFAULT_TICKERS_HK = [
    "00700", "09988", "03690", "00939", "01299",
]

_DEFAULTS = {
    Market.CN: DEFAULT_TICKERS_CN,
    Market.US: DEFAULT_TICKERS_US,
    Market.HK: DEFAULT_TICKERS_HK,
}


def get_default_tickers(market: "str | Market" = Market.US) -> list:
    """返回某市场的默认演示股票池。"""
    if isinstance(market, str):
        try:
            market = Market[market.upper()]
        except KeyError:
            market = Market.US
    return list(_DEFAULTS.get(market, DEFAULT_TICKERS_US))
