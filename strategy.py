"""
무한매수법 V4.0 전략 코어 (라오어 순정 / 언이 변형판 파라미터화).

봇 재사용 목적: 순수 로직만 담는다. 데이터·체결·IO 없음.
- compute_orders(state, ref_close, sma5, params) -> 그날 깔 주문 리스트
- apply_day(state, orders, ohlc, params)        -> 체결 시뮬 + T/모드/사이클 갱신

근거: docs/uni-calculator-analysis.md (언이 Apps Script 해부),
      docs/strategy-v4-spec.md (라오어 원문).
"""
from dataclasses import dataclass, field
import math


# ----------------------------------------------------------------------
# 파라미터 (C: 변형판 토글)
# ----------------------------------------------------------------------
@dataclass
class Params:
    ticker: str
    n: int = 40                    # 분할수
    principal: float = 10000.0     # 시작 원금
    base_yield_pct: float = 15.0   # 별% base + 지정가매도 목표 + 리버스 복귀선
    large_pct: float = 10.0        # 큰수 기준 %
    big_num_base: str = "close"    # 'close'(언이) | 'avg'(라오어) — 큰수 기준가
    reverse_ref: str = "sma5"      # 'sma5'(언이) | 'star'(라오어) — 리버스 매수/매도 기준선
    compounding: bool = True       # 잔금에 실현손익 누적(언이) | 단리(라오어)
    ladder_max: int = 5            # 대폭락 사다리 최대 단수


def laoer_params(ticker, n=40, principal=10000.0):
    """라오어 순정 근사: 별% 15(TQQQ)/20(SOXL), 큰수=평단기준, 리버스=별지점, 단리."""
    by = 15.0 if ticker.upper() == "TQQQ" else 20.0
    return Params(ticker, n, principal, base_yield_pct=by,
                  big_num_base="avg", reverse_ref="star", compounding=False)


def uni_params(ticker, n=40, principal=10000.0, base_yield_pct=15.0):
    """언이 시트 1.1: 목표수익률 커스텀, 큰수=종가기준, 리버스=5일평균, 복리."""
    return Params(ticker, n, principal, base_yield_pct=base_yield_pct,
                  big_num_base="close", reverse_ref="sma5", compounding=True)


# ----------------------------------------------------------------------
# 상태
# ----------------------------------------------------------------------
@dataclass
class State:
    shares: int = 0
    avg: float = 0.0
    T: float = 0.0
    mode: str = "NORMAL"        # NORMAL | REVERSE
    prev_mode: str = "NORMAL"   # 직전일 모드 (리버스 1일차 판정용)
    realized_cum: float = 0.0   # 누적 실현손익
    cycles: int = 0             # 완료 사이클 수
    cycle_start_invested: float = 0.0  # (참고용)


def available_balance(s: State, p: Params) -> float:
    invested = s.shares * s.avg
    bal = p.principal - invested + (s.realized_cum if p.compounding else 0.0)
    return bal


def star_pct(T: float, mode: str, p: Params) -> float:
    """별%(P). 라오어 별%표의 일반화: base_yield * (1 - 2T/n). 리버스=0."""
    if mode != "NORMAL":
        return 0.0
    return p.base_yield_pct * (1 - 2 * T / p.n)


def big_num(ref_close: float, s: State, p: Params) -> float:
    base = ref_close if (p.big_num_base == "close" or s.avg <= 0) else s.avg
    return base * (1 + p.large_pct / 100.0)


# ----------------------------------------------------------------------
# 주문 생성
# ----------------------------------------------------------------------
# 주문 표현: ("BUY", price, qty) / ("SELL_LOC", price, qty) /
#            ("SELL_LIMIT", price, qty) / ("SELL_MOC", None, qty)
def compute_orders(s: State, ref_close: float, sma5: float, p: Params):
    n = p.n
    P = star_pct(s.T, s.mode, p)
    large = big_num(ref_close, s, p)
    bal = available_balance(s, p)

    first_day_reverse = (s.mode == "REVERSE" and s.prev_mode == "NORMAL")

    if s.mode == "REVERSE":
        amt = max(0.0, bal / 4.0)
    else:
        amt = max(0.0, bal / max(0.1, n - s.T))

    star_sell = max(0.01, s.avg * (1 + P / 100.0)) if s.shares > 0 else 0.0
    star_buy = max(0.01, star_sell - 0.01) if s.shares > 0 else 0.0
    rev_buy = max(0.01, sma5 - 0.01)
    sell_limit = s.avg * (1 + p.base_yield_pct / 100.0) if s.shares > 0 else 0.0

    buys = []
    sells = []
    base_qty = 0

    # ---- 매수 ----
    if first_day_reverse:
        pass  # 리버스 1일차: 매수 금지
    else:
        if s.shares <= 0:
            amt = p.principal / n
            base_qty = math.floor(amt / large)
            if base_qty > 0:
                buys.append(("BUY", round(large, 2), base_qty))
        elif s.mode == "REVERSE":
            # 언이=5일평균-0.01 / 라오어=별지점(P=0→평단)-0.01
            rprice = rev_buy if p.reverse_ref == "sma5" else star_buy
            base_qty = math.floor(amt / rprice) if rprice > 0 else 0
            if base_qty > 0:
                buys.append(("BUY", round(rprice, 2), base_qty))
        elif s.T < n / 2:  # 전반전: 절반 별지점 + 나머지 평단
            price1 = min(star_buy, large)
            price2 = min(s.avg, large)
            q1 = math.floor((amt * 0.5) / price1) if price1 > 0 else 0
            q2 = max(0, (math.floor(amt / price2) if price2 > 0 else 0) - q1)
            base_qty = q1 + q2
            if q1 > 0:
                buys.append(("BUY", round(price1, 2), q1))
            if q2 > 0:
                buys.append(("BUY", round(price2, 2), q2))
        else:  # 후반전: 전액 별지점(큰수 상한)
            fp = min(star_buy, large)
            base_qty = math.floor(amt / fp) if fp > 0 else 0
            if base_qty > 0:
                buys.append(("BUY", round(fp, 2), base_qty))

        # 대폭락 사다리: tierPrice = amt/(base_qty+k), 큰수 미만, 최대 ladder_max단
        tiers = 0
        cq = base_qty + 1
        for _ in range(15):
            if cq <= 0:
                cq += 1
                continue
            tp = amt / cq
            if 0 < tp < large:
                buys.append(("BUY", round(tp, 2), 1))
                tiers += 1
            if tiers >= p.ladder_max:
                break
            cq += 1

    # ---- 매도 ----
    if s.shares > 0:
        if s.mode == "REVERSE":
            rq = math.floor(s.shares / (n / 2))
            if rq > 0:
                if first_day_reverse:
                    sells.append(("SELL_MOC", None, rq))
                else:
                    ref = sma5 if p.reverse_ref == "sma5" else s.avg  # 라오어=별지점(P=0→평단)
                    sells.append(("SELL_LOC", round(ref, 2), rq))
        else:
            qq = math.floor(s.shares * 0.25)
            if qq > 0:
                sells.append(("SELL_LOC", round(star_sell, 2), qq))      # 쿼터
            if s.shares - qq > 0:
                sells.append(("SELL_LIMIT", round(sell_limit, 2), s.shares - qq))  # 지정가 3/4

    return {"buys": buys, "sells": sells, "amt": amt, "large": large, "P": P}


# ----------------------------------------------------------------------
# 하루 체결 시뮬 + 상태 갱신
# ----------------------------------------------------------------------
def apply_day(s: State, orders: dict, ohlc, p: Params):
    """orders(전일 생성)를 당일 OHLC에 체결. 새 State + 당일정보 반환."""
    o, h, l, c = ohlc
    n = p.n
    old_shares, old_avg, old_T, old_mode = s.shares, s.avg, s.T, s.mode

    sold_limit = sold_quarter = sold_rev = 0
    realized = 0.0

    for kind, price, qty in orders["sells"]:
        if qty <= 0:
            continue
        if kind == "SELL_MOC":
            sold_rev += qty
            realized += qty * (c - old_avg)
        elif kind == "SELL_LOC":
            if c >= price:  # 종가가 매도점 이상 → 체결 (종가)
                if old_mode == "REVERSE":
                    sold_rev += qty
                    realized += qty * (c - old_avg)
                else:
                    sold_quarter += qty
                    realized += qty * (c - old_avg)
        elif kind == "SELL_LIMIT":
            if h >= price:  # 장중 고가가 지정가 도달 → 지정가 체결
                sold_limit += qty
                realized += qty * (price - old_avg)

    bought = 0
    cost = 0.0
    for kind, price, qty in orders["buys"]:
        if kind == "BUY" and c <= price:  # 종가가 지정가 이하 → LOC 매수(종가 체결)
            bought += qty
            cost += qty * c

    total_sold = sold_limit + sold_quarter + sold_rev
    remaining_old = old_shares - total_sold
    if remaining_old < 0:
        remaining_old = 0
    new_shares = remaining_old + bought

    if new_shares > 0:
        new_avg = (remaining_old * old_avg + cost) / new_shares
    else:
        new_avg = 0.0

    # ---- T / 모드 갱신 ----
    T, mode, cycle_end = update_t_mode(old_shares, new_shares, old_avg, new_avg, old_T, old_mode, c, p)

    new = State(
        shares=new_shares, avg=new_avg, T=T, mode=mode, prev_mode=old_mode,
        realized_cum=s.realized_cum + realized, cycles=s.cycles, cycle_start_invested=s.cycle_start_invested,
    )

    action = "SELL" if new_shares < old_shares else ("BUY" if new_shares > old_shares else "NONE")
    info = {
        "action": action, "sold_limit": sold_limit, "sold_quarter": sold_quarter,
        "sold_rev": sold_rev, "bought": bought, "realized": realized,
        "cycle_end": cycle_end, "close": c,
    }

    if cycle_end:
        new.cycles += 1
        # 사이클 리셋 (실현손익 누적은 유지)
        new.shares = 0
        new.avg = 0.0
        new.T = 0.0
        new.mode = "NORMAL"
        new.prev_mode = "NORMAL"

    return new, info


# ----------------------------------------------------------------------
# T / 모드 갱신 (언이 스크립트 분기 복제) — 백테스트·라이브 공용
# ----------------------------------------------------------------------
def update_t_mode(old_shares, new_shares, old_avg, new_avg, old_T, old_mode, close, p):
    """보유수량 변화(old→new)로부터 T·모드·사이클종료 판정. 순수 함수."""
    n = p.n
    action = "SELL" if new_shares < old_shares else ("BUY" if new_shares > old_shares else "NONE")
    qQty = math.floor(old_shares * 0.25)
    T = old_T
    mode = old_mode
    cycle_end = False

    if action == "SELL":
        if new_shares <= 0:
            cycle_end = True
            T = 0.0
        elif new_shares <= old_shares * 0.60:  # 상황2: 지정가 3/4 체결 (+재매수 가능)
            if new_shares > qQty:
                T = old_T * 0.25 + (0.5 if close > old_avg else 1.0)
            else:
                T = old_T * 0.25
        else:  # 상황3: 일반 쿼터 매도
            T = old_T * 0.75 if old_mode == "NORMAL" else old_T * (1 - 2.0 / n)
    elif action == "BUY":
        if old_mode == "NORMAL":
            if old_shares == 0:
                T = old_T + 1.0
            elif old_T < n / 2:
                T = old_T + (0.5 if close > old_avg else 1.0)
            else:
                T = old_T + 1.0
        else:  # REVERSE 매수
            T = old_T + (n - old_T) * 0.25

    if not cycle_end:
        if mode == "NORMAL" and T >= n - 1:
            mode = "REVERSE"
        elif mode == "REVERSE" and close > new_avg * (1 - p.base_yield_pct / 100.0):
            mode = "NORMAL"

    return T, mode, cycle_end


def reconcile(s: State, observed_shares: int, observed_avg: float, realized_delta: float,
              close: float, p: Params):
    """라이브용: 브로커에서 읽은 실제 보유(observed)로 상태 갱신.

    s = 직전 저장 상태(전일 종료 시점). observed_* = 지금 브로커 실제 포지션.
    realized_delta = 그 사이 발생한 실현손익(브로커 체결내역에서 계산해 전달).
    반환: (새 State, cycle_end)
    """
    T, mode, cycle_end = update_t_mode(
        s.shares, observed_shares, s.avg, observed_avg, s.T, s.mode, close, p)

    new = State(
        shares=observed_shares, avg=observed_avg, T=T, mode=mode, prev_mode=s.mode,
        realized_cum=s.realized_cum + realized_delta, cycles=s.cycles,
    )
    if cycle_end:
        new.cycles += 1
        new.shares = 0
        new.avg = 0.0
        new.T = 0.0
        new.mode = "NORMAL"
        new.prev_mode = "NORMAL"
    return new, cycle_end
