"""
무한매수법 V4.0 백테스터.

- yfinance 일봉(분할/배당 조정) 로드, 로컬 캐시.
- strategy.compute_orders 로 전일 종가 기준 주문 생성 → 당일 OHLC 로 체결(apply_day).
- 인과 보장: d일 주문은 d-1 종가/5일평균으로 생성, d일 OHLC로 체결(룩어헤드 없음).

지표: 최종 평가금, 실현손익, 미실현, CAGR, MDD, 사이클 수.
"""
import os
import math
import datetime as dt

import pandas as pd
import yfinance as yf

import strategy as st

CACHE = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(CACHE, exist_ok=True)


def load_ohlc(ticker, start, end):
    path = os.path.join(CACHE, f"{ticker}_{start}_{end}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    else:
        df = yf.download(ticker, start=start, end=end, interval="1d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close"]].dropna()
        df.to_csv(path)
    df["sma5"] = df["Close"].rolling(5, min_periods=1).mean()
    return df


def run(params: st.Params, df: pd.DataFrame, verbose_log=None):
    closes = df["Close"].tolist()
    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    opens = df["Open"].tolist()
    sma5s = df["sma5"].tolist()
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    N = len(df)

    s = st.State()
    # day0 기준으로 첫 주문 생성
    orders = st.compute_orders(s, closes[0], sma5s[0], params)

    equity_curve = []
    rows = []
    peak_equity = params.principal
    max_dd = 0.0
    reverse_days = 0
    min_equity = params.principal

    for d in range(1, N):
        ohlc = (opens[d], highs[d], lows[d], closes[d])
        s, info = st.apply_day(s, orders, ohlc, params)
        if s.mode == "REVERSE":
            reverse_days += 1

        # 평가금 = 원금 + 누적실현 + 미실현
        unreal = s.shares * (closes[d] - s.avg) if s.shares > 0 else 0.0
        equity = params.principal + s.realized_cum + unreal
        equity_curve.append(equity)
        peak_equity = max(peak_equity, equity)
        min_equity = min(min_equity, equity)
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_dd = max(max_dd, dd)

        # 다음날 주문 (오늘 종가/5일평균 기준)
        orders = st.compute_orders(s, closes[d], sma5s[d], params)

        if verbose_log is not None:
            rows.append({
                "date": dates[d], "close": round(closes[d], 2), "mode": s.mode,
                "shares": s.shares, "avg": round(s.avg, 2), "T": round(s.T, 3),
                "realized_cum": round(s.realized_cum, 2), "equity": round(equity, 2),
                "action": info["action"], "bought": info["bought"],
                "sold": info["sold_limit"] + info["sold_quarter"] + info["sold_rev"],
                "cycle_end": info["cycle_end"],
            })

    last_close = closes[-1]
    unreal = s.shares * (last_close - s.avg) if s.shares > 0 else 0.0
    final_equity = params.principal + s.realized_cum + unreal
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = (final_equity / params.principal) ** (1 / years) - 1 if final_equity > 0 and years > 0 else float("nan")

    if verbose_log is not None:
        pd.DataFrame(rows).to_csv(verbose_log, index=False)

    return {
        "ticker": params.ticker, "n": params.n, "principal": params.principal,
        "years": round(years, 2), "final_equity": round(final_equity, 2),
        "realized_cum": round(s.realized_cum, 2), "open_shares": s.shares,
        "open_avg": round(s.avg, 2), "unrealized": round(unreal, 2),
        "ret_pct": round((final_equity / params.principal - 1) * 100, 1),
        "cagr_pct": round(cagr * 100, 1) if cagr == cagr else float("nan"),
        "mdd_pct": round(max_dd * 100, 1), "cycles": s.cycles,
        "end_mode": s.mode, "end_T": round(s.T, 2),
        "reverse_days": reverse_days, "min_equity": round(min_equity, 0),
        "trough_pct": round((min_equity / params.principal - 1) * 100, 1),
        "equity_curve": equity_curve, "dates": dates[1:],
    }


def fmt(r):
    return (f"{r['ticker']:5} | 평가금 ${r['final_equity']:>10,.0f} | "
            f"수익률 {r['ret_pct']:>7.1f}% | CAGR {r['cagr_pct']:>6.1f}% | "
            f"MDD {r['mdd_pct']:>5.1f}% | 사이클 {r['cycles']:>2} | "
            f"실현 ${r['realized_cum']:>9,.0f} | 미실현 ${r['unrealized']:>8,.0f} | "
            f"종료 {r['end_mode']:7} T={r['end_T']:.1f} 보유 {r['open_shares']}")


def main():
    end = dt.date.today()
    start = end - dt.timedelta(days=365 * 3 + 10)
    start_s, end_s = start.isoformat(), end.isoformat()

    print(f"\n=== 무한매수법 V4.0 백테스트 ===")
    print(f"기간: {start_s} ~ {end_s} (약 3년)  원금: $10,000/종목  분할: 40\n")

    for ticker in ["TQQQ", "SOXL"]:
        df = load_ohlc(ticker, start_s, end_s)
        print(f"[{ticker}] {df.index[0].date()} ~ {df.index[-1].date()}  "
              f"{len(df)}일  시작 ${df['Close'].iloc[0]:.2f} → 종료 ${df['Close'].iloc[-1]:.2f} "
              f"(buy&hold {(df['Close'].iloc[-1]/df['Close'].iloc[0]-1)*100:+.0f}%)")

        for label, params in [
            ("라오어순정", st.laoer_params(ticker)),
            ("언이변형 ", st.uni_params(ticker, base_yield_pct=(15.0 if ticker == "TQQQ" else 20.0))),
        ]:
            log = os.path.join(CACHE, f"log_{ticker}_{label.strip()}.csv")
            r = run(params, df, verbose_log=log)
            print("   " + label + " : " + fmt(r))
        print()


if __name__ == "__main__":
    main()
