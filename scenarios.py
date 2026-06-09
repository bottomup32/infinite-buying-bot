"""약세장 다중 시나리오 스트레스 테스트. 리버스 모드 검증 목적."""
import datetime as dt
import backtest as bt
import strategy as st

SCENARIOS = [
    ("코로나폭락",   "2020-01-01", "2020-09-30"),
    ("2018Q4하락",   "2018-08-01", "2019-03-31"),
    ("2022베어",     "2022-01-01", "2023-01-31"),
    ("고점→바닥",    "2021-11-01", "2023-06-30"),
    ("2025관세폭락", "2025-01-01", "2025-09-30"),
]
TICKERS = ["TQQQ", "SOXL"]


def variants(ticker):
    by = 15.0 if ticker == "TQQQ" else 20.0
    return [("라오어", st.laoer_params(ticker)),
            ("언이", st.uni_params(ticker, base_yield_pct=by))]


def main():
    print("\n=== 약세장 다중 시나리오 (원금 $10,000/종목, 40분할) ===")
    print("trough% = 기간중 최저 평가금 낙폭 | rev = 리버스 진입 일수\n")
    hdr = f"{'시나리오':<13}{'종목':<6}{'변형':<7}{'수익률':>8}{'MDD':>7}{'trough':>8}{'rev':>5}{'cyc':>5}{'끝모드':>9}{'끝T':>6}"
    for name, start, end in SCENARIOS:
        print(f"\n■ {name}  ({start} ~ {end})")
        for ticker in TICKERS:
            df = bt.load_ohlc(ticker, start, end)
            bh = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
            print(f"   {ticker}  Buy&Hold {bh:+.0f}%   "
                  f"(${df['Close'].iloc[0]:.1f} → ${df['Close'].iloc[-1]:.1f}, {len(df)}일)")
            print("   " + hdr)
            for vlabel, params in variants(ticker):
                r = bt.run(params, df)
                print("   " + f"{'':<13}{ticker:<6}{vlabel:<7}"
                      f"{r['ret_pct']:>7.1f}%{r['mdd_pct']:>6.1f}%{r['trough_pct']:>7.1f}%"
                      f"{r['reverse_days']:>5}{r['cycles']:>5}{r['end_mode']:>9}{r['end_T']:>6.1f}")


if __name__ == "__main__":
    main()
