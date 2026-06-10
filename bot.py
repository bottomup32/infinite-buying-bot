"""
무한매수법 V4.0 자동매매 봇 (Alpaca paper).

하루 1회(미장 마감 ~15분 전) 실행:
 1) 브로커에서 실제 보유·체결 읽어 상태(T·모드·실현손익) 갱신 (= 언이 시트 실시간판)
 2) 오늘 낼 주문(LOC 매수 사다리 / 쿼터 LOC 매도 / 지정가 매도 / 리버스 MOC) 계산
 3) (--live 시) 기존 미체결 취소 후 제출
 4) Google Sheet 대시보드 갱신 + 기록 누적 + 상태 영속화

상태 저장: Google Sheet '_상태' 탭(우선) → 없으면 로컬 state/*.json.
안전장치: 기본 dry-run. 실제 제출은 --live. 장 마감 임박일 때만 제출(--force로 무시).
"""
import os
import sys
import json
import argparse
import datetime as dt
from dataclasses import asdict

try:  # Windows 콘솔 이모지/한글 출력
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import strategy as st
import config
import broker_alpaca as bk


# ----------------------------------------------------------------------
# 시트 연결 (상태저장 + 대시보드 공용)
# ----------------------------------------------------------------------
def get_sheet():
    if not (config.DASHBOARD_SHEET_ID and config.GOOGLE_SA_JSON):
        return None
    try:
        import sheets_dashboard as dash
        return dash.connect(config.GOOGLE_SA_JSON, config.DASHBOARD_SHEET_ID)
    except Exception as e:
        print(f"⚠️ 시트 연결 실패(로컬 상태로 진행): {e}")
        return None


# ----------------------------------------------------------------------
# 상태 로드/저장 (시트 우선, 로컬 폴백)
# ----------------------------------------------------------------------
def _local_path(ticker):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    return os.path.join(config.STATE_DIR, f"{ticker}.json")


def load_state(ticker, sheet_states):
    if sheet_states and ticker in sheet_states:
        d, last_run = sheet_states[ticker]
        return st.State(**d), last_run
    path = _local_path(ticker)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        last_run = d.pop("last_run", None)
        return st.State(**{k: d[k] for k in d if k in st.State.__dataclass_fields__}), last_run
    return None, None


def save_state_local(ticker, state, last_run):
    d = asdict(state)
    d["last_run"] = last_run
    with open(_local_path(ticker), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def seed_state(obs_shares, obs_avg, p):
    if obs_shares > 0 and obs_avg > 0:
        T = (obs_shares * obs_avg / p.principal) * p.n
        mode = "REVERSE" if T >= p.n - 1 else "NORMAL"
    else:
        T, mode = 0.0, "NORMAL"
    return st.State(shares=obs_shares, avg=obs_avg, T=T, mode=mode, prev_mode="NORMAL")


# ----------------------------------------------------------------------
# 주문 제출
# ----------------------------------------------------------------------
def submit_orders(broker, symbol, orders, log):
    broker.cancel_open(symbol)
    for kind, price, qty in orders["buys"]:
        try:
            broker.submit_loc(symbol, "BUY", qty, price)
            log.append(f"  ✅ 매수 LOC ${price:.2f}/{qty}주 제출")
        except Exception as e:
            log.append(f"  ⚠️ 매수 LOC ${price:.2f}/{qty}주 실패: {e}")
    for kind, price, qty in orders["sells"]:
        try:
            if kind == "SELL_LOC":
                broker.submit_loc(symbol, "SELL", qty, price)
                log.append(f"  ✅ 쿼터 매도 LOC ${price:.2f}/{qty}주 제출")
            elif kind == "SELL_LIMIT":
                broker.submit_limit_day(symbol, "SELL", qty, price)
                log.append(f"  ✅ 지정가 매도 ${price:.2f}/{qty}주 제출")
            elif kind == "SELL_MOC":
                broker.submit_moc(symbol, "SELL", qty)
                log.append(f"  ✅ MOC 매도 {qty}주 제출")
        except Exception as e:
            log.append(f"  ⚠️ 매도 제출 실패: {e}")


# ----------------------------------------------------------------------
# 메인
# ----------------------------------------------------------------------
def run_once(live=False, use_sheet=True, force=False):
    now = dt.datetime.now()
    now_iso = now.isoformat()
    print(f"\n=== 무한매수법 봇 {now:%Y-%m-%d %H:%M:%S}  "
          f"[{'LIVE 주문제출' if live else 'DRY-RUN'}] ===")

    if not config.ALPACA_API_KEY:
        print("⚠️ ALPACA_API_KEY 없음 — .env/Secret 설정 필요. 중단.")
        return

    broker = bk.Broker(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.ALPACA_PAPER)

    # 주문 윈도우 = 장 열려있고 CLS 마감(15:58 ET) 전. GitHub cron 지연(최대 2시간+)
    # 흡수 위해 넓게(마감 4분~6시간 전). 시트/상태는 항상 갱신(가시성).
    in_window = True
    if live and not force:
        clk = broker.clock()
        m = clk["minutes_to_close"]
        in_window = bool(clk["is_open"] and m is not None and 4 <= m <= 390)
        if in_window:
            print(f"⏰ 장중 (마감 {round(m)}분 전) — 주문 진행")
        else:
            print(f"⏸ 장 외/마감직전 → 주문 생략(시트만 갱신). "
                  f"is_open={clk['is_open']} 마감까지={None if m is None else round(m)}분")
    effective_live = live and (force or in_window)

    account = broker.account()
    print(f"계좌 Equity ${account['equity']:,.2f} | 현금 ${account['cash']:,.2f} | BP ${account['buying_power']:,.2f}")

    ss = get_sheet() if use_sheet else None
    sheet_states = {}
    if ss is not None:
        try:
            import sheets_dashboard as dash
            sheet_states = dash.load_states(ss)
        except Exception as e:
            print(f"⚠️ 상태 로드 경고: {e}")

    views, history_rows, new_states = [], [], {}

    for p in config.PORTFOLIO:
        sym = p.ticker
        obs_shares, obs_avg = broker.position(sym)
        ref_close, sma5 = broker.ref_close_and_sma5(sym)
        if ref_close is None:
            print(f"[{sym}] 일봉 조회 실패 — 건너뜀")
            continue

        state, last_run = load_state(sym, sheet_states)
        first = state is None
        if first:
            state = seed_state(obs_shares, obs_avg, p)
            print(f"[{sym}] 첫 실행 — 보유 {obs_shares}주 평단 ${obs_avg:.2f} 시드 (T={state.T:.2f})")

        action = "NONE"
        if not first:
            after = dt.datetime.fromisoformat(last_run) if last_run else (now - dt.timedelta(days=4))
            realized_delta = 0.0
            try:
                for fobj in broker.filled_orders_since(sym, after):
                    if fobj["side"] == "SELL":
                        realized_delta += fobj["qty"] * (fobj["price"] - state.avg)
            except Exception as e:
                print(f"[{sym}] 체결내역 조회 경고: {e}")
            prev_shares = state.shares
            state, cycle_end = st.reconcile(state, obs_shares, obs_avg, realized_delta, ref_close, p)
            action = "사이클종료🎉" if cycle_end else (
                "SELL" if obs_shares < prev_shares else "BUY" if obs_shares > prev_shares else "NONE")

        orders = st.compute_orders(state, ref_close, sma5, p)
        P = orders["P"]
        star_sell = max(0.01, state.avg * (1 + P / 100.0)) if state.shares > 0 else 0.0

        log = []
        if effective_live:
            # 같은날 앞선 cron이 이미 주문 깔았으면 재제출 스킵 (LOC/지정가는 종가/EOD까지 유효)
            if not force and broker.has_open_orders(sym):
                log.append("  ⏭ 오늘 이미 주문 있음 — 유지(재제출 생략)")
            else:
                submit_orders(broker, sym, orders, log)
        else:
            for kind, price, qty in orders["buys"]:
                log.append(f"  (preview) 매수 LOC ${price:.2f}/{qty}주")
            for kind, price, qty in orders["sells"]:
                log.append(f"  (preview) {kind} ${0 if price is None else price:.2f}/{qty}주")

        pos_val = obs_shares * ref_close
        unreal = obs_shares * (ref_close - obs_avg) if obs_shares > 0 else 0.0
        print(f"\n[{sym}] {state.mode} T={state.T:.3f}/{p.n} 보유 {obs_shares}주 평단 ${obs_avg:.2f} "
              f"평가손익 ${unreal:+,.2f} 실현 ${state.realized_cum:+,.2f} 사이클 {state.cycles}")
        print(f"     별지점 ${star_sell:.2f} | 큰수 ${orders['large']:.2f} | 1회매수금 ${orders['amt']:,.2f}")
        for line in log:
            print(line)

        views.append({
            "ticker": sym, "n": p.n, "principal": p.principal, "mode": state.mode,
            "T": state.T, "shares": obs_shares, "avg": obs_avg,
            "position_value": pos_val, "unrealized": unreal,
            "unrealized_pct": (ref_close / obs_avg - 1) * 100 if obs_avg > 0 else 0.0,
            "realized_cum": state.realized_cum, "cycles": state.cycles,
            "star_sell": star_sell, "large": orders["large"], "amt": orders["amt"],
            "ref_close": ref_close, "orders_text": orders["buys"] + orders["sells"],
        })
        history_rows.append([
            now.strftime("%Y-%m-%d %H:%M"), sym, state.mode, f"{state.T:.3f}",
            f"{ref_close:.2f}", obs_shares, f"{obs_avg:.2f}", f"{unreal:+.2f}",
            f"{state.realized_cum:+.2f}", state.cycles, action,
            "LIVE제출" if effective_live else ("preview" if live else "dry-run"),
        ])
        new_states[sym] = (state, now_iso)
        save_state_local(sym, state, now_iso)

    # 시트 저장 (상태 + 대시보드 + 기록)
    if ss is not None:
        try:
            import sheets_dashboard as dash
            dash.save_states(ss, new_states)
            dash.update_dashboard(ss, account, views, now=now)
            dash.append_history(ss, history_rows)
            print("\n📊 Google Sheet 상태·대시보드·기록 갱신 완료")
        except Exception as e:
            print(f"\n⚠️ 시트 갱신 실패: {e}")
    else:
        print("\n(시트 미설정 — 로컬 상태만 저장)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실제 주문 제출")
    ap.add_argument("--no-sheet", action="store_true", help="Google Sheet 생략")
    ap.add_argument("--force", action="store_true", help="장 마감 가드 무시(테스트용)")
    args = ap.parse_args()
    run_once(live=args.live, use_sheet=not args.no_sheet, force=args.force)
