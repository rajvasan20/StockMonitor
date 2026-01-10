import datetime as dt
from io import BytesIO

import pandas as pd
import streamlit as st
import yfinance as yf


st.set_page_config(page_title="India Stock OHLCV Downloader", layout="centered")

st.title("India Stock Daily OHLCV Downloader")
st.caption("Fetch last 5 years of daily prices (Open, High, Low, Close, Volume) from Yahoo Finance.")

# Default example ticker for NSE: RELIANCE.NS
default_ticker = "RELIANCE.NS"

nifty50_fallback = [
    "RELIANCE.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "INFY.NS",
    "TCS.NS",
    "KOTAKBANK.NS",
    "LT.NS",
    "SBIN.NS",
    "AXISBANK.NS",
    "ITC.NS",
    "ASIANPAINT.NS",
    "HINDUNILVR.NS",
    "BAJFINANCE.NS",
    "BAJAJFINSV.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "ULTRACEMCO.NS",
    "NESTLEIND.NS",
    "POWERGRID.NS",
    "BHARTIARTL.NS",
    "NTPC.NS",
    "HCLTECH.NS",
    "WIPRO.NS",
    "TECHM.NS",
    "ONGC.NS",
    "COALINDIA.NS",
    "GRASIM.NS",
    "JSWSTEEL.NS",
    "TATASTEEL.NS",
    "ADANIPORTS.NS",
    "CIPLA.NS",
    "DRREDDY.NS",
    "BAJAJ-AUTO.NS",
    "EICHERMOT.NS",
    "HDFCLIFE.NS",
    "HEROMOTOCO.NS",
    "BRITANNIA.NS",
    "SHREECEM.NS",
    "UPL.NS",
    "DIVISLAB.NS",
    "INDUSINDBK.NS",
    "SBILIFE.NS",
    "TATAMOTORS.NS",
    "BPCL.NS",
    "HINDALCO.NS",
    "IOC.NS",
    "M&M.NS",
    "ADANIENT.NS",
    "APOLLOHOSP.NS",
]

try:
    nifty_tickers = yf.tickers_nifty50()
    if not nifty_tickers:
        nifty_tickers = nifty50_fallback
except Exception:
    nifty_tickers = nifty50_fallback

ticker = st.selectbox(
    "Select Nifty 50 stock (Yahoo Finance ticker)",
    options=nifty_tickers,
    index=nifty_tickers.index(default_ticker) if default_ticker in nifty_tickers else 0,
)

col1, col2 = st.columns(2)
with col1:
    start_date = (dt.date.today() - dt.timedelta(days=5 * 365))
    st.write(f"Start date (fixed to 5 years ago): {start_date}")
with col2:
    end_date = dt.date.today()
    st.write(f"End date: {end_date}")

daily_button = st.button("Fetch daily data")
weekly_button = st.button("Fetch weekly data")
monthly_button = st.button("Fetch monthly data")

@st.cache_data(show_spinner=True)
def fetch_ohlcv(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    if not ticker:
        return pd.DataFrame()
    data = yf.download(ticker, start=start, end=end, interval="1d", auto_adjust=False)
    # Ensure index is a column named Date
    if not data.empty:
        data = data.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    return data

@st.cache_data(show_spinner=True)
def fetch_ohlcv_weekly(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    if not ticker:
        return pd.DataFrame()
    data = yf.download(ticker, start=start, end=end, interval="1wk", auto_adjust=False)
    if not data.empty:
        data = data.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    return data

@st.cache_data(show_spinner=True)
def fetch_ohlcv_monthly(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    if not ticker:
        return pd.DataFrame()
    data = yf.download(ticker, start=start, end=end, interval="1mo", auto_adjust=False)
    if not data.empty:
        data = data.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    return data

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI(14), MACD(12,26,9), and month-year column to the dataframe."""
    if df.empty:
        return df

    df = df.copy()

    # Ensure date is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"])

    # Month short name column, e.g. Jan
    df["month"] = df["date"].dt.strftime("%b")

    # Month_Year column, e.g. Jan_2025
    df["month_year"] = df["date"].dt.strftime("%b_%Y")

    # RSI(14) based on adjusted closing price (Wilder-style smoothing)
    window = 14
    price = df.get("adj_close", df["close"])
    delta = price.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's RSI via exponentially weighted moving averages with alpha = 1/window
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    df["rsi_14"] = rsi

    # EMAs based on closing price
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

    # DMAs (simple moving averages) based on closing price
    df["dma_20"] = df["close"].rolling(window=20, min_periods=1).mean()
    df["dma_50"] = df["close"].rolling(window=50, min_periods=1).mean()
    df["dma_200"] = df["close"].rolling(window=200, min_periods=1).mean()

    # MACD (12, 26, 9) based on closing price
    ema_short = df["close"].ewm(span=12, adjust=False).mean()
    ema_long = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema_short - ema_long
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    df["macd_12_26"] = macd
    df["macd_signal_9"] = signal
    df["macd_hist"] = hist

    # Per-row signal based on EMAs and MACD histogram
    df["signal_action"] = "Neutral / Hold"
    df["signal_detail"] = "No strong trend signal. Consider using with other analysis."

    # Use 1D numpy arrays for comparisons to avoid pandas alignment issues
    close = df["close"].to_numpy().ravel()
    ema20 = df["ema_20"].to_numpy().ravel()
    ema50 = df["ema_50"].to_numpy().ravel()
    ema200 = df["ema_200"].to_numpy().ravel()

    ema_bull = (close > ema20) & (ema20 > ema50) & (ema50 > ema200)
    ema_bear = (close < ema20) & (ema20 < ema50) & (ema50 < ema200)

    macd_hist = df["macd_hist"].to_numpy().ravel()

    buy_mask = ema_bull & (macd_hist > 0)
    sell_mask = ema_bear & (macd_hist < 0)
    bullish_mask = (macd_hist > 0) & ~buy_mask
    bearish_mask = (macd_hist < 0) & ~sell_mask

    df.loc[buy_mask, "signal_action"] = "Potential BUY"
    df.loc[buy_mask, "signal_detail"] = "Price above 20/50/200 EMAs in alignment (uptrend) and MACD histogram positive (bullish momentum)."

    df.loc[sell_mask, "signal_action"] = "Potential SELL"
    df.loc[sell_mask, "signal_detail"] = "Price below 20/50/200 EMAs in alignment (downtrend) and MACD histogram negative (bearish momentum)."

    df.loc[bullish_mask, "signal_action"] = "Bullish bias"
    df.loc[bullish_mask, "signal_detail"] = "MACD histogram positive; price showing bullish bias but EMAs not fully aligned."

    df.loc[bearish_mask, "signal_action"] = "Bearish bias"
    df.loc[bearish_mask, "signal_detail"] = "MACD histogram negative; price showing bearish bias but EMAs not fully aligned."

    return df

def compute_monthly_strategy_stats(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute monthly spread/spread% and RSI-based statistics for strategy analysis.

    Returns
    -------
    monthly_spread_stats : DataFrame
        Per-month high/low, spreads, and daily spread distribution stats.
    monthly_rsi_stats : DataFrame
        Per-month max/min RSI with corresponding close and spreads, plus RSI regime counts.
    spread_summary : DataFrame
        Overall mean/median/std of month_spread and month_spread_pct across all months.
    """

    if df.empty or "date" not in df.columns:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    work = df.copy()

    if not pd.api.types.is_datetime64_any_dtype(work["date"]):
        work["date"] = pd.to_datetime(work["date"])

    # Daily spreads — be defensive in case of duplicate column names
    high_col = work["high"]
    if isinstance(high_col, pd.DataFrame):
        high_col = high_col.iloc[:, 0]

    low_col = work["low"]
    if isinstance(low_col, pd.DataFrame):
        low_col = low_col.iloc[:, 0]

    daily_spread_series = pd.to_numeric(high_col, errors="coerce") - pd.to_numeric(low_col, errors="coerce")
    work["daily_spread"] = daily_spread_series

    # Ensure we work with a single Series for low prices when computing % spread
    low_series = pd.to_numeric(low_col, errors="coerce")
    low_series = low_series.mask(low_series == 0, pd.NA)
    daily_spread_pct_series = daily_spread_series / low_series * 100
    work["daily_spread_pct"] = daily_spread_pct_series

    # Use existing month_year column if present, else derive from date
    if "month_year" not in work.columns:
        work["month_year"] = work["date"].dt.strftime("%b_%Y")

    # If required columns are missing for any reason, skip stats safely
    required_cols = {"date", "high", "low", "daily_spread", "daily_spread_pct", "month_year"}
    if not required_cols.issubset(set(work.columns)):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    grp = work.groupby("month_year", sort=True)

    # Per-month spread stats
    monthly = grp.agg(
        month_start=("date", "min"),
        month_end=("date", "max"),
        month_high=("high", "max"),
        month_low=("low", "min"),
        daily_spread_mean=("daily_spread", "mean"),
        daily_spread_median=("daily_spread", "median"),
        daily_spread_std=("daily_spread", "std"),
        daily_spread_pct_mean=("daily_spread_pct", "mean"),
        daily_spread_pct_median=("daily_spread_pct", "median"),
        daily_spread_pct_std=("daily_spread_pct", "std"),
    )

    monthly["month_spread"] = monthly["month_high"] - monthly["month_low"]
    monthly["month_spread_pct"] = monthly["month_spread"] / monthly["month_low"].replace(0, pd.NA) * 100

    # Overall stats for spreads across months
    spread_summary = (
        monthly[["month_spread", "month_spread_pct"]]
        .agg(["mean", "median", "std"])
        .rename_axis("statistic")
    )

    # RSI-based stats per month
    rsi_rows: list[dict] = []
    for name, sub in grp:
        sub = sub.dropna(subset=["rsi_14"]).copy()
        if sub.empty:
            continue

        # Day with max RSI
        idx_rsi_max = sub["rsi_14"].idxmax()
        row_max = sub.loc[idx_rsi_max]
        max_rsi = float(row_max["rsi_14"])
        max_close = float(row_max["close"])
        max_high = float(row_max["high"])
        max_low = float(row_max["low"])
        max_spread = max_high - max_low
        max_spread_pct = max_spread / max_low * 100 if max_low != 0 else float("nan")

        # Day with min RSI
        idx_rsi_min = sub["rsi_14"].idxmin()
        row_min = sub.loc[idx_rsi_min]
        min_rsi = float(row_min["rsi_14"])
        min_close = float(row_min["close"])
        min_high = float(row_min["high"])
        min_low = float(row_min["low"])
        min_spread = min_high - min_low
        min_spread_pct = min_spread / min_low * 100 if min_low != 0 else float("nan")

        # RSI regime counts
        days_rsi_above_60 = int((sub["rsi_14"] > 60).sum())
        days_rsi_below_40 = int((sub["rsi_14"] < 40).sum())
        total_days = int(len(sub))

        rsi_rows.append(
            {
                "month_year": name,
                "total_days_with_rsi": total_days,
                "days_rsi_above_60": days_rsi_above_60,
                "days_rsi_below_40": days_rsi_below_40,
                "max_rsi": max_rsi,
                "max_rsi_close": max_close,
                "max_rsi_spread": max_spread,
                "max_rsi_spread_pct": max_spread_pct,
                "min_rsi": min_rsi,
                "min_rsi_close": min_close,
                "min_rsi_spread": min_spread,
                "min_rsi_spread_pct": min_spread_pct,
            }
        )

    monthly_rsi_stats = pd.DataFrame(rsi_rows).set_index("month_year") if rsi_rows else pd.DataFrame()

    return monthly, monthly_rsi_stats, spread_summary

def show_signals(df: pd.DataFrame, timeframe: str) -> None:
    if df.empty or "rsi_14" not in df.columns or "macd_hist" not in df.columns or "macd_12_26" not in df.columns or "macd_signal_9" not in df.columns:
        return

    latest = df.iloc[-1]
    rsi = latest.get("rsi_14")
    macd = latest.get("macd_12_26")
    signal = latest.get("macd_signal_9")
    hist = latest.get("macd_hist")

    # Ensure we are working with scalar numeric values before formatting
    try:
        rsi_val = float(rsi)
        macd_val = float(macd)
        signal_val = float(signal)
        hist_val = float(hist)
    except (TypeError, ValueError):
        st.info(f"Not enough or invalid data to compute signals on {timeframe} timeframe.")
        return

    if pd.isna([rsi_val, macd_val, signal_val, hist_val]).any():
        st.info(f"Not enough data yet to compute signals on {timeframe} timeframe.")
        return

    message_lines = [
        f"Latest {timeframe} RSI(14): {rsi_val:.2f}",
        f"Latest {timeframe} MACD: {macd_val:.4f}",
        f"Latest {timeframe} Signal: {signal_val:.4f}",
        f"Latest {timeframe} MACD Histogram: {hist_val:.4f}",
    ]

    # Use precomputed per-row signal if available
    action = latest.get("signal_action", "Neutral / Hold")
    detail = latest.get("signal_detail", "No strong overbought/oversold signal. Consider using with other analysis.")

    st.subheader(f"{timeframe} Signals")
    for line in message_lines:
        st.write(line)
    st.info(f"Suggestion: {action} — {detail}")

if daily_button:
    if not ticker.strip():
        st.error("Please enter a valid ticker symbol.")
    else:
        with st.spinner("Fetching data from Yahoo Finance..."):
            df = fetch_ohlcv(ticker.strip(), start_date, end_date)

        if df.empty:
            st.warning("No data returned. Check the ticker symbol or try a different one.")
        else:
            df = add_indicators(df)
            st.success(f"Fetched {len(df)} rows of DAILY data for {ticker.strip()} (with indicators).")

            st.subheader("Preview")
            st.dataframe(df.head(20))

            # Monthly strategy analytics (spreads and RSI-based stats)
            monthly_stats, monthly_rsi_stats, spread_summary = compute_monthly_strategy_stats(df)

            if not monthly_stats.empty:
                st.subheader("Monthly price spread stats")
                st.dataframe(monthly_stats)

            if not spread_summary.empty:
                st.subheader("Overall spread statistics across months")
                st.dataframe(spread_summary)

            if not monthly_rsi_stats.empty:
                st.subheader("Monthly RSI / entry-exit stats")
                st.dataframe(monthly_rsi_stats)

            # Current month support and resistance levels (based on daily data)
            today_sr = dt.date.today()
            month_start_sr = today_sr.replace(day=1)
            if month_start_sr.month == 12:
                month_end_sr = dt.date(month_start_sr.year + 1, 1, 1)
            else:
                month_end_sr = dt.date(month_start_sr.year, month_start_sr.month + 1, 1)

            mask_month_sr = (df["date"] >= pd.Timestamp(month_start_sr)) & (df["date"] < pd.Timestamp(month_end_sr))
            df_month_sr = df.loc[mask_month_sr]

            if not df_month_sr.empty:
                try:
                    month_high_sr = float(df_month_sr["high"].max())
                except Exception:
                    month_high_sr = float("nan")

                try:
                    month_low_sr = float(df_month_sr["low"].min())
                except Exception:
                    month_low_sr = float("nan")

                st.subheader("Current Month Support & Resistance")
                st.write(f"Support (approx. monthly low): {month_low_sr:.2f}")
                st.write(f"Resistance (approx. monthly high): {month_high_sr:.2f}")

            # Build CSV for download
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            filename = f"{ticker.strip()}_5y_daily_ohlcv_with_indicators.csv"

            st.download_button(
                label="Download CSV",
                data=csv_bytes,
                file_name=filename,
                mime="text/csv",
            )

            # Build Excel with charts for daily data
            try:
                excel_buffer = BytesIO()

                # Filter for last 1 year and last 6 months based on date column
                max_date = df["date"].max()
                last_1y_start = max_date - pd.Timedelta(days=365)
                last_6m_start = max_date - pd.Timedelta(days=182)

                df_last1y = df[df["date"] >= last_1y_start].reset_index(drop=True)
                df_last6m = df[df["date"] >= last_6m_start].reset_index(drop=True)

                # Ensure no MultiIndex columns before writing to Excel
                df_to_write = df.copy()
                df_to_write.columns = [str(c) for c in df_to_write.columns]
                df_last1y.columns = [str(c) for c in df_last1y.columns]
                df_last6m.columns = [str(c) for c in df_last6m.columns]

                with pd.ExcelWriter(excel_buffer, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
                    # Write raw data and filtered views
                    df_to_write.to_excel(writer, sheet_name="AllData", index=False)
                    df_last1y.to_excel(writer, sheet_name="Last1Year", index=False)
                    df_last6m.to_excel(writer, sheet_name="Last6Months", index=False)

                    workbook = writer.book
                    sheet_1y = writer.sheets["Last1Year"]
                    sheet_6m = writer.sheets["Last6Months"]

                    n1 = len(df_last1y)
                    n6 = len(df_last6m)

                    if n1 > 1:
                        # 1) Candlestick chart with EMAs for last 1 year
                        chart_candle = workbook.add_chart({"type": "stock", "subtype": "candlestick"})

                        # Add OHLC series (open, high, low, close)
                        for col_idx, col_name in enumerate(["open", "high", "low", "close"], start=1):
                            chart_candle.add_series(
                                {
                                    "name": ["Last1Year", 0, col_idx],
                                    "categories": ["Last1Year", 1, 0, n1, 0],  # dates
                                    "values": ["Last1Year", 1, col_idx, n1, col_idx],
                                }
                            )

                        chart_candle.set_title({"name": "Last 1 Year - Candlestick with EMAs"})
                        chart_candle.set_x_axis({"name": "Date"})
                        chart_candle.set_y_axis({"name": "Price"})

                        # Line chart for EMAs on top of candlestick chart
                        chart_emas_1y = workbook.add_chart({"type": "line"})
                        ema_series_added = False
                        for ema_col in ["ema_20", "ema_50", "ema_200"]:
                            if ema_col in df_last1y.columns:
                                col_idx = df_last1y.columns.get_loc(ema_col)
                                chart_emas_1y.add_series(
                                    {
                                        "name": ["Last1Year", 0, col_idx],
                                        "categories": ["Last1Year", 1, 0, n1, 0],
                                        "values": ["Last1Year", 1, col_idx, n1, col_idx],
                                    }
                                )
                                ema_series_added = True

                        if ema_series_added:
                            chart_emas_1y.set_y_axis({"name": "EMAs"})
                            # Combine EMAs with candlestick only if we have EMA series
                            chart_candle.combine(chart_emas_1y)

                        # Place candlestick (with EMAs overlaid if present) on the Last1Year sheet
                        sheet_1y.insert_chart("J2", chart_candle, {"x_offset": 15, "y_offset": 10})

                        # MACD and RSI line chart for last 1 year
                        chart_macd_rsi = workbook.add_chart({"type": "line"})
                        macd_series_added = False
                        for ind_col in ["macd_12_26", "macd_signal_9", "macd_hist", "rsi_14"]:
                            if ind_col in df_last1y.columns:
                                col_idx = df_last1y.columns.get_loc(ind_col)
                                chart_macd_rsi.add_series(
                                    {
                                        "name": ["Last1Year", 0, col_idx],
                                        "categories": ["Last1Year", 1, 0, n1, 0],
                                        "values": ["Last1Year", 1, col_idx, n1, col_idx],
                                    }
                                )
                                macd_series_added = True

                        if macd_series_added:
                            chart_macd_rsi.set_title({"name": "Last 1 Year - MACD & RSI"})
                            chart_macd_rsi.set_x_axis({"name": "Date"})
                            chart_macd_rsi.set_y_axis({"name": "Value"})

                            sheet_1y.insert_chart("J20", chart_macd_rsi, {"x_offset": 15, "y_offset": 10})

                    if n6 > 1:
                        # 2) Close price line chart with EMAs for last 6 months
                        chart_6m = workbook.add_chart({"type": "line"})
                        chart_6m_series_added = False

                        # Close price
                        if "close" in df_last6m.columns:
                            close_idx_6 = df_last6m.columns.get_loc("close")
                            chart_6m.add_series(
                                {
                                    "name": ["Last6Months", 0, close_idx_6],
                                    "categories": ["Last6Months", 1, 0, n6, 0],
                                    "values": ["Last6Months", 1, close_idx_6, n6, close_idx_6],
                                }
                            )
                            chart_6m_series_added = True

                        # EMAs
                        for ema_col in ["ema_20", "ema_50", "ema_200"]:
                            if ema_col in df_last6m.columns:
                                col_idx = df_last6m.columns.get_loc(ema_col)
                                chart_6m.add_series(
                                    {
                                        "name": ["Last6Months", 0, col_idx],
                                        "categories": ["Last6Months", 1, 0, n6, 0],
                                        "values": ["Last6Months", 1, col_idx, n6, col_idx],
                                    }
                                )
                                chart_6m_series_added = True

                        if chart_6m_series_added:
                            chart_6m.set_title({"name": "Last 6 Months - Close with EMAs"})
                            chart_6m.set_x_axis({"name": "Date"})
                            chart_6m.set_y_axis({"name": "Price"})

                            sheet_6m.insert_chart("J2", chart_6m, {"x_offset": 15, "y_offset": 10})

                excel_bytes = excel_buffer.getvalue()

                excel_filename = f"{ticker.strip()}_daily_with_indicators_and_charts.xlsx"
                st.download_button(
                    label="Download Excel with charts",
                    data=excel_bytes,
                    file_name=excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.warning(f"Failed to build Excel with charts: {e}")

            show_signals(df, timeframe="Daily")

if weekly_button:
    if not ticker.strip():
        st.error("Please enter a valid ticker symbol.")
    else:
        with st.spinner("Fetching weekly data from Yahoo Finance..."):
            df_w = fetch_ohlcv_weekly(ticker.strip(), start_date, end_date)

        if df_w.empty:
            st.warning("No weekly data returned. Check the ticker symbol or try a different one.")
        else:
            df_w = add_indicators(df_w)
            st.success(f"Fetched {len(df_w)} rows of WEEKLY data for {ticker.strip()} (with indicators).")

            st.subheader("Weekly Preview")
            st.dataframe(df_w.head(20))

            csv_bytes_w = df_w.to_csv(index=False).encode("utf-8")
            filename_w = f"{ticker.strip()}_5y_weekly_ohlcv_with_indicators.csv"

            st.download_button(
                label="Download Weekly CSV",
                data=csv_bytes_w,
                file_name=filename_w,
                mime="text/csv",
            )

            show_signals(df_w, timeframe="Weekly")

if monthly_button:
    if not ticker.strip():
        st.error("Please enter a valid ticker symbol.")
    else:
        with st.spinner("Fetching monthly data from Yahoo Finance..."):
            df_m = fetch_ohlcv_monthly(ticker.strip(), start_date, end_date)

        if df_m.empty:
            st.warning("No monthly data returned. Check the ticker symbol or try a different one.")
        else:
            df_m = add_indicators(df_m)
            st.success(f"Fetched {len(df_m)} rows of MONTHLY data for {ticker.strip()} (with indicators).")

            st.subheader("Monthly Preview")
            st.dataframe(df_m.head(20))

            csv_bytes_m = df_m.to_csv(index=False).encode("utf-8")
            filename_m = f"{ticker.strip()}_5y_monthly_ohlcv_with_indicators.csv"

            st.download_button(
                label="Download Monthly CSV",
                data=csv_bytes_m,
                file_name=filename_m,
                mime="text/csv",
            )

            show_signals(df_m, timeframe="Monthly")

# Nifty 50 monthly overview tab
tab_overview, = st.tabs(["Nifty 50 monthly overview"])

with tab_overview:
    st.subheader("Nifty 50 monthly RSI and spread overview")

    # Always use the current calendar month for the overview
    today = dt.date.today()
    month_start = today.replace(day=1)

    # Month end is first day of next month
    if month_start.month == 12:
        month_end = dt.date(month_start.year + 1, 1, 1)
    else:
        month_end = dt.date(month_start.year, month_start.month + 1, 1)

    st.write(f"Showing stats for current month ({month_start.strftime('%b_%Y')}) from {month_start} to {month_end - dt.timedelta(days=1)}")

    timeframe = st.selectbox("Timeframe", ["Daily", "Weekly", "Monthly"], index=0)

    run_overview = st.button("Run Nifty 50 overview for selected timeframe")

    if run_overview:
        rows = []

        # Choose appropriate fetch function based on timeframe
        if timeframe == "Daily":
            fetch_fn = fetch_ohlcv
        elif timeframe == "Weekly":
            fetch_fn = fetch_ohlcv_weekly
        else:
            fetch_fn = fetch_ohlcv_monthly

        # Use ~1.5 years of history so RSI(14) on any timeframe has ample warm-up
        history_start = today - dt.timedelta(days=550)

        for t in nifty_tickers:
            df_t = fetch_fn(t, history_start, today)
            if df_t.empty:
                continue

            df_t = add_indicators(df_t)
            if df_t.empty or "rsi_14" not in df_t.columns:
                continue

            # Current RSI (latest available row)
            latest_row = df_t.iloc[-1]
            try:
                current_rsi = float(latest_row.get("rsi_14"))
            except (TypeError, ValueError):
                current_rsi = float("nan")

            # Filter to selected month for max RSI and spread stats
            mask_month = (df_t["date"] >= pd.Timestamp(month_start)) & (df_t["date"] < pd.Timestamp(month_end))
            df_month = df_t.loc[mask_month]
            if df_month.empty:
                continue

            max_rsi_month = float(df_month["rsi_14"].max()) if not df_month["rsi_14"].isna().all() else float("nan")

            # Ensure scalar floats for month high/low and spread%
            try:
                month_high_val = float(df_month["high"].max())
            except Exception:
                month_high_val = float("nan")

            try:
                month_low_val = float(df_month["low"].min())
            except Exception:
                month_low_val = float("nan")

            if month_low_val and month_low_val != 0:
                month_spread_pct_val = (month_high_val - month_low_val) / month_low_val * 100
            else:
                month_spread_pct_val = float("nan")

            # Simple signal based on current RSI
            if current_rsi < 40:
                rsi_signal = "Buy"
            elif current_rsi > 60:
                rsi_signal = "Sell"
            else:
                rsi_signal = "Hold"

            rows.append(
                {
                    "ticker": t,
                    "timeframe": timeframe,
                    "current_rsi": current_rsi,
                    "rsi_signal": rsi_signal,
                    "max_rsi_in_month": max_rsi_month,
                    "month_high": month_high_val,
                    "month_low": month_low_val,
                    "month_spread_pct": month_spread_pct_val,
                }
            )

        if rows:
            overview_df = pd.DataFrame(rows).sort_values("ticker")
            st.dataframe(overview_df)
        else:
            st.info("No data available for the selected month across Nifty 50 tickers.")
    else:
        st.info("Click the button above to fetch the latest monthly overview for all Nifty 50 tickers.")

st.markdown("---")
st.markdown(
    """**Usage notes**

- Use Yahoo Finance tickers for Indian stocks, e.g. `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`.
- The app always fetches roughly the last 5 years of daily data.
- Columns: `date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`."""
)
