"""골든테스트 — 봇 전략 코어가 라오어 원문 + 언이 스크립트와 일치하는지 검증.
근거값: docs/uni-calculator-analysis.md, docs/strategy-v4-spec.md.
실행: python test_strategy.py
"""
import math
import strategy as st

PASS = 0
FAIL = 0


def chk(name, got, exp, tol=1e-6):
    global PASS, FAIL
    ok = abs(got - exp) <= tol if isinstance(exp, (int, float)) else (got == exp)
    print(("✅" if ok else "❌") + f" {name}: got={got} exp={exp}")
    PASS += ok
    FAIL += (not ok)


# ── 1. 별%(P) 공식 ────────────────────────────────────────────
p_tqqq40 = st.uni_params("TQQQ", n=40, base_yield_pct=15.0)
chk("별% TQQQ40 T=0", st.star_pct(0, "NORMAL", p_tqqq40), 15.0)
chk("별% TQQQ40 T=4 (=15-0.75*4)", st.star_pct(4, "NORMAL", p_tqqq40), 12.0)
chk("별% TQQQ40 T=20 (절반→0)", st.star_pct(20, "NORMAL", p_tqqq40), 0.0)
chk("별% TQQQ40 T=32 (후반 음수)", st.star_pct(32, "NORMAL", p_tqqq40), -9.0)
p_soxl20 = st.uni_params("SOXL", n=20, base_yield_pct=20.0)
chk("별% SOXL20 T=8.6 (=20-2*8.6)", st.star_pct(8.6, "NORMAL", p_soxl20), 2.8)
chk("별% 리버스=0", st.star_pct(5, "REVERSE", p_tqqq40), 0.0)

# ── 2. 별지점 예시 (분석문서 §3: 평단38.30 T8.6 → 39.37) ──────
s = st.State(shares=110, avg=38.30, T=8.6, mode="NORMAL")
o = st.compute_orders(s, ref_close=39.0, sma5=39.0, p=p_soxl20)
star_sell = max(0.01, s.avg * (1 + o["P"] / 100))
chk("별지점 SOXL20 평단38.30 T8.6", round(star_sell, 2), 39.37, tol=0.01)

# ── 3. 1회매수금 (분석문서 §4: 잔금19522 T1 40분할 → 500.56) ──
# 단리(laoer): bal = principal - shares*avg = 20000 - 478 = 19522
pl = st.laoer_params("TQQQ", n=40, principal=20000.0)
s = st.State(shares=10, avg=47.8, T=1.0, mode="NORMAL")  # invested=478
o = st.compute_orders(s, ref_close=47.8, sma5=47.8, p=pl)
chk("1회매수금 19522/(40-1)", round(o["amt"], 2), 500.56, tol=0.01)

# ── 4. 리버스 매도수량 (분석문서 §9: n40 d=20, 200→10) ───────
pu = st.uni_params("TQQQ", n=40, base_yield_pct=15.0)
s = st.State(shares=200, avg=20.0, T=39.0, mode="REVERSE", prev_mode="REVERSE")
o = st.compute_orders(s, ref_close=15.0, sma5=15.0, p=pu)
rev_sell = [q for k, pr, q in o["sells"] if k in ("SELL_LOC", "SELL_MOC")]
chk("리버스 매도 floor(200/20)", rev_sell[0] if rev_sell else -1, 10)
# 시퀀스 floor 확인
chk("리버스 floor(190/20)", math.floor(190 / 20), 9)
chk("리버스 floor(181/20)", math.floor(181 / 20), 9)
chk("리버스 floor(172/20)", math.floor(172 / 20), 8)

# ── 5. T 갱신 분기 (update_t_mode) ───────────────────────────
n = 40
# 최초매수 0→10
T, m, ce = st.update_t_mode(0, 10, 0, 50, 0.0, "NORMAL", 50, pu)
chk("T 최초매수 0→1", T, 1.0)
# 전반전 매수 close>avg → +0.5
T, m, ce = st.update_t_mode(10, 12, 50, 50, 5.0, "NORMAL", 55, pu)
chk("T 전반전 close>avg +0.5", T, 5.5)
# 전반전 매수 close<avg → +1
T, m, ce = st.update_t_mode(10, 12, 50, 50, 5.0, "NORMAL", 45, pu)
chk("T 전반전 close<avg +1", T, 6.0)
# 후반전 매수 → +1
T, m, ce = st.update_t_mode(10, 12, 50, 50, 25.0, "NORMAL", 60, pu)
chk("T 후반전 매수 +1", T, 26.0)
# 쿼터매도 NORMAL → *0.75
T, m, ce = st.update_t_mode(100, 75, 50, 50, 8.0, "NORMAL", 55, pu)
chk("T 쿼터매도 *0.75", T, 6.0)
# 상황2: 3/4 지정가 + 재매수 close>avg
T, m, ce = st.update_t_mode(100, 30, 50, 50, 8.0, "NORMAL", 55, pu)
chk("T 상황2 재매수 close>avg =oldT*0.25+0.5", T, 8 * 0.25 + 0.5)
# 사이클 종료
T, m, ce = st.update_t_mode(50, 0, 50, 0, 7.0, "NORMAL", 60, pu)
chk("사이클종료 cycle_end", ce, True)
chk("사이클종료 T=0", T, 0.0)
# 리버스 매수 T+=(n-T)*0.25
T, m, ce = st.update_t_mode(100, 110, 20, 20, 38.0, "REVERSE", 18, pu)
chk("T 리버스매수 +=(n-T)*0.25", T, 38 + (40 - 38) * 0.25)
# 리버스 쿼터매도 *(1-2/n)
T, m, ce = st.update_t_mode(100, 95, 20, 20, 38.0, "REVERSE", 18, pu)
chk("T 리버스쿼터매도 *(1-2/40)", T, 38 * (1 - 2 / 40))

# ── 6. 모드 전환 ─────────────────────────────────────────────
T, m, ce = st.update_t_mode(380, 390, 30, 30, 38.0, "NORMAL", 28, pu)  # T→39≥n-1
chk("모드 NORMAL→REVERSE (T≥n-1)", m, "REVERSE")
# 리버스 복귀: close > avg*(1-15/100)=avg*0.85
T, m, ce = st.update_t_mode(100, 95, 50, 50, 38.0, "REVERSE", 50 * 0.86, pu)
chk("모드 REVERSE→NORMAL (회복선 위)", m, "NORMAL")

# ── 7. 최초매수 주문 + 사다리 (라이브와 동일: TQQQ n40 원금1만) ──
pf = st.uni_params("TQQQ", n=40, principal=10000.0, base_yield_pct=15.0)
o = st.compute_orders(st.State(), ref_close=76.27, sma5=81.66, p=pf)
chk("최초 큰수 =76.27*1.1", o["large"], round(76.27 * 1.1, 10), tol=0.01)
chk("최초 1회매수금 =10000/40", o["amt"], 250.0)
first = o["buys"][0]
chk("최초 baseQty =floor(250/83.90)", first[2], math.floor(250 / (76.27 * 1.1)))
# 사다리: 모두 큰수 미만, 최대 5단, 각 1주
ladder = o["buys"][1:]
chk("사다리 ≤5단", len(ladder) <= 5, True)
chk("사다리 전부 큰수 미만", all(pr < o["large"] for _, pr, _ in ladder), True)
chk("사다리 각 1주", all(q == 1 for _, _, q in ladder), True)
chk("사다리 1단가 =250/(base+1)", ladder[0][1], round(250 / (first[2] + 1), 2), tol=0.01)

# ── 8. 전반전 매수구조 (절반 별지점 + 나머지 평단) ────────────
s = st.State(shares=20, avg=70.0, T=4.0, mode="NORMAL")
o = st.compute_orders(s, ref_close=72.0, sma5=72.0, p=pf)
buys = [b for b in o["buys"]]
chk("전반전 매수주문 ≥2 (별지점+평단)", len([b for b in buys if b[2] >= 1]) >= 2, True)

print(f"\n=== 결과: {PASS} PASS / {FAIL} FAIL ===")
exit(1 if FAIL else 0)
