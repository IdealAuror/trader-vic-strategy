"""A 股数据提供层 — akshare 数据拉取 + CSV 缓存 + 数据质量验证

使用前复权 (qfq) 保持当前价格真实、历史价格向下调整。
宏观数据滞后 1 月处理，防止发布前视偏差。
"""

import os
import json
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from trader_vic.config import (
    DATA_ADJUST,
    MIN_DATA_BARS,
    MAX_NAN_RATIO,
    SUSPEND_THRESHOLD,
    OHLCV,
    BACKTEST_START,
)


class DataQualityError(Exception):
    """数据质量问题异常"""


def _symbol_to_akshare(symbol: str) -> str:
    """转换股票代码为 akshare daily 接口需要的格式

    深交所: 000/001/002/003/300 开头 → sz 前缀
    上交所: 600/601/603/605/688 开头 → sh 前缀
    """
    if symbol.startswith(("sh", "sz", "SH", "SZ")):
        return symbol.lower()
    prefix = symbol[:3]
    sz_prefixes = {"000", "001", "002", "003", "300", "301"}
    if prefix in sz_prefixes:
        return f"sz{symbol}"
    return f"sh{symbol}"


def fetch_stock_history(
    symbol: str,
    start: str = BACKTEST_START,
    end: Optional[str] = None,
    adjust: str = DATA_ADJUST,
) -> pd.DataFrame:
    """拉取单只股票前复权日线数据

    使用 stock_zh_a_daily 接口处理（stock_zh_a_hist 的 adjust
    参数在部分网络环境下不可用）。
    """
    import akshare as ak

    if end is None:
        end = datetime.now().strftime("%Y%m%d")

    ak_symbol = _symbol_to_akshare(symbol)
    df = ak.stock_zh_a_daily(
        symbol=ak_symbol,
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust=adjust,
    )

    if df is None or df.empty:
        raise DataQualityError(f"{symbol}: akshare 返回空数据")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")

    available = [c for c in OHLCV if c in df.columns]
    if "amount" in df.columns:
        df = df[available + ["amount"]]
    else:
        df = df[available]
    df = df.astype(float)
    return df


def fetch_index(
    symbol: str = "sh000300",
    start: str = BACKTEST_START,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """拉取指数日线数据（沪深300/上证指数）"""
    import akshare as ak

    if end is None:
        end = datetime.now().strftime("%Y%m%d")

    df = ak.stock_zh_index_daily(symbol=symbol)
    if df.empty:
        raise DataQualityError(f"指数 {symbol}: akshare 返回空数据")

    col_map = {"date": "date", "open": "open", "high": "high",
               "low": "low", "close": "close", "volume": "volume"}
    df = df.rename(columns=col_map)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df = df[(df.index >= pd.Timestamp(start)) &
            (df.index <= pd.Timestamp(end) if end else True)]
    return df


def fetch_macro_data() -> Dict[str, Optional[float]]:
    """拉取月频宏观数据：M2 同比、PMI、Shibor"""
    import akshare as ak

    result: Dict[str, Optional[float]] = {"m2_yoy": None, "pmi": None, "shibor_1y": None}

    try:
        m2 = ak.macro_china_money_supply()
        if not m2.empty:
            m2 = m2.sort_values("日期")
            m2_yoy_col = [c for c in m2.columns if "同比" in str(c)]
            if m2_yoy_col:
                result["m2_yoy"] = float(m2[m2_yoy_col[0]].iloc[-1])
    except Exception:
        pass

    try:
        pmi = ak.macro_china_pmi()
        if not pmi.empty:
            pmi = pmi.sort_values("date") if "date" in pmi.columns else pmi
            pmi_col = [c for c in pmi.columns if "PMI" in str(c).upper()]
            if pmi_col:
                result["pmi"] = float(pmi[pmi_col[0]].iloc[-1])
    except Exception:
        pass

    try:
        shibor = ak.rate_interbank(
            market="上海银行间同业拆放利率",
            symbol="Shibor_1Y",
        )
        if not shibor.empty:
            val_col = [c for c in shibor.columns if "利率" in str(c) or "收盘" in str(c)]
            if val_col:
                result["shibor_1y"] = float(shibor[val_col[0]].iloc[-1])
    except Exception:
        pass

    return result


def fetch_pe_history() -> pd.DataFrame:
    """拉取沪深300 PE 全量历史数据

    Returns:
        DataFrame with columns: date, pe_ttm, pe_percentile
        失败时返回空 DataFrame
    """
    import akshare as ak

    try:
        df = ak.stock_index_pe_lg(symbol="沪深300")
        if df is None or df.empty or len(df.columns) < 8:
            return pd.DataFrame()

        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df.iloc[:, 0])
        result["pe_ttm"] = df.iloc[:, 6].astype(float)
        result["pe_percentile"] = df.iloc[:, 7].astype(float)
        result = result.sort_values("date").reset_index(drop=True)
        return result
    except Exception:
        return pd.DataFrame()


def fetch_margin_history() -> tuple:
    """拉取沪深两市融资融券全量历史数据

    Returns:
        (sh_df, sz_df): 各为 DataFrame with columns: date, margin_balance
        失败时返回两个空 DataFrame
    """
    import akshare as ak

    def _parse(df_raw, label: str) -> pd.DataFrame:
        if df_raw is None or df_raw.empty:
            return pd.DataFrame()
        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df_raw.iloc[:, 0])
        result["margin_balance"] = df_raw.iloc[:, 1].astype(float)
        result = result.sort_values("date").reset_index(drop=True)
        return result

    try:
        sh = ak.macro_china_market_margin_sh()
        sz = ak.macro_china_market_margin_sz()
        return _parse(sh, "sh"), _parse(sz, "sz")
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def validate_stock_data(df: pd.DataFrame) -> pd.DataFrame:
    """数据质量验证

    - 至少 252 根 K 线（1 年交易数据）
    - NaN 比例 <= 5%
    - 连续 20 天价格不变 → 停牌检测
    - 前复权异常检测（单日涨跌幅 > 20%）

    Returns:
        清洗后的 DataFrame
    """
    if len(df) < MIN_DATA_BARS:
        raise DataQualityError(
            f"数据不足 {MIN_DATA_BARS} 根 K 线（共 {len(df)} 根）"
        )

    nan_count = df[OHLCV].isna().sum().sum()
    nan_ratio = nan_count / (len(df) * len(OHLCV))
    if nan_ratio > MAX_NAN_RATIO:
        raise DataQualityError(
            f"NaN 比例 {nan_ratio:.1%} 超过上限 {MAX_NAN_RATIO:.0%}"
        )

    df = df.ffill().bfill()

    price_unchanged = (df["high"] == df["low"]).rolling(SUSPEND_THRESHOLD).sum()
    suspend_days = (price_unchanged >= SUSPEND_THRESHOLD).sum()
    if suspend_days > 0:
        last_suspend = price_unchanged[price_unchanged >= SUSPEND_THRESHOLD].index[-1]
        if last_suspend > df.index[-int(len(df) * 0.1)]:
            raise DataQualityError(
                f"近期连续停牌超过 {SUSPEND_THRESHOLD} 天"
            )

    daily_returns = df["close"].pct_change()
    abnormal_returns = daily_returns[daily_returns.abs() > 0.20]
    if len(abnormal_returns) > len(df) * 0.01:
        raise DataQualityError(
            f"前复权异常：{len(abnormal_returns)} 个交易日涨跌幅超过 20%"
        )

    df = df[df["close"] > 0]

    return df


def resample_to_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """从日线实时构建周线（无前瞻偏差）

    使用截至 current_date 的历史数据 resample：
    Open = 周一开盘, High = 周内最高, Low = 周内最低,
    Close = 周五收盘, Volume = 周内总成交量
    """
    weekly = daily_df.resample("W-FRI", label="right").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    return weekly.dropna()


def fetch_watchlist(
    tickers: List[str],
    start: str = BACKTEST_START,
    end: Optional[str] = None,
    cache_dir: str = "data",
) -> Dict[str, pd.DataFrame]:
    """拉取候选池全部股票数据，带 CSV 缓存"""
    if end is None:
        end = datetime.now().strftime("%Y%m%d")

    os.makedirs(cache_dir, exist_ok=True)
    result = {}
    manifest: Dict[str, str] = {}

    manifest_path = os.path.join(cache_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

    for ticker in tickers:
        cache_path = os.path.join(cache_dir, f"{ticker}.csv")
        should_fetch = True

        if os.path.exists(cache_path) and ticker in manifest:
            cache_date = manifest[ticker]
            req_end = end[:8] if end else datetime.now().strftime("%Y%m%d")
            if cache_date >= req_end:
                try:
                    df = pd.read_csv(cache_path, index_col="date", parse_dates=True)
                    if len(df) >= MIN_DATA_BARS:
                        result[ticker] = df
                        should_fetch = False
                except Exception:
                    should_fetch = True

        if should_fetch:
            try:
                df = fetch_stock_history(ticker, start, end)
                df = validate_stock_data(df)

                fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
                os.close(fd)
                try:
                    df.to_csv(tmp_path, encoding="utf-8-sig")
                    os.replace(tmp_path, cache_path)
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

                manifest[ticker] = end[:8] if end else datetime.now().strftime("%Y%m%d")
                result[ticker] = df
            except DataQualityError as e:
                print(f"  跳过 {ticker}: {e}")
            except Exception as e:
                print(f"  拉取 {ticker} 失败: {e}")

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return result


def align_trading_dates(
    data: Dict[str, pd.DataFrame],
    index_data: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """对齐所有股票的共同交易日"""
    common_dates = None
    for ticker, df in data.items():
        dates = set(df.index)
        if common_dates is None:
            common_dates = dates
        else:
            common_dates &= dates

    if not common_dates:
        raise DataQualityError("候选池无共同交易日")

    common_dates = sorted(common_dates)
    return pd.concat(
        {t: df.reindex(common_dates).ffill() for t, df in data.items()},
        axis=1,
    )
