# 언이 자동계산 시트 1.1 — Apps Script 알고리즘 해부 (실측)

> 출처: "무매 v4.0 자동계산 시트_1.1 (목표수익률 커스텀 버전) by 언이" Google Apps Script (2026/05/08판).
> 라오어 V4.0 원리 기반의 **커스텀 변형판**. 백테스터 구현 시 이 알고리즘을 그대로 재현할지, 라오어 원문(`strategy-v4-spec.md`)을 따를지는 선택. 차이는 §"라오어 대비 차이" 참조.
>
> ⚠️ 저작권: 라오어 방법론·언이 시트 모두 외부 재배포 금지. 개인 분석·개발용 내부 문서.

## 0. 시트 셀 매핑
| 셀 | 내용 |
|---|---|
| B2 | 종목(ticker) |
| B3 | 분할수 n |
| B4 | 시작원금 principal |
| B5 | 종가 close (`=GOOGLEFINANCE(B2,"price")`) |
| B6 | 보유수량 shares |
| B7 | 평단가 avg |
| B8 | 큰수 기준 % (기본 10) |
| D2 | 현재 모드 (NORMAL/REVERSE/CYCLE_END) |
| D3 | 현재 T값 |
| D4 | 현재 P(별%) |
| D5 | 남은 잔금 |
| D6 | 목표수익률 % (startP) |
| D7 | 큰수 가격 |
| D8 | 5일 평균 sma5 (`=AVERAGE(QUERY(GOOGLEFINANCE(...최근15일...) limit 5))`) |
| 체크박스 G2~G5 | startCycle / updateDaily / resetDatabase / 수식복구 |

## 1. 핵심 공식

```
P(별%)   = (mode==NORMAL) ? targetYield × (1 − 2·T/n) : 0
큰수      = close × (1 + largePct/100)            // 평단 아님, 종가 기준. 매수가 상한(cap)
amt(1회) = (mode==REVERSE) ? balance/4 : balance / max(0.1, n−T)

별지점_매도 = max(0.01, avg × (1 + P/100))
별지점_매수 = 별지점_매도 − 0.01
리버스매수가 = sma5 − 0.01
지정가_매도 = avg × (1 + targetYield/100)
리버스복귀선 = avg × (1 − targetYield/100)
```
- 목표15·n40 → P=15−0.75T (라오어 TQQQ40과 동일). 목표20·n20 → 20−2T (SOXL20과 동일). **즉 라오어 별%표의 일반화.**

## 2. 매수 주문 생성 (updateDaily)

```
baseQty = 0
if (mode==REVERSE && prevMode==NORMAL):           # 리버스 1일차
    매수 금지
elif shares <= 0:                                  # 최초매수
    amt = principal / n
    baseQty = floor(amt / 큰수)
    주문: [LOC] 큰수 / baseQty주
elif mode==REVERSE:                                # 리버스 2일차+
    baseQty = floor(amt / 리버스매수가)
    주문: [LOC] 리버스매수가 이하 / baseQty주
elif T < n/2:                                      # 전반전
    price1 = min(별지점_매수, 큰수)
    price2 = min(avg, 큰수)
    q1 = floor(amt×0.5 / price1)                   # 절반 → 별지점
    q2 = max(0, floor(amt / price2) − q1)          # 나머지 → 평단
    baseQty = q1 + q2
    주문: [LOC] price1 / q1주  +  [LOC] price2 / q2주
else:                                              # 후반전
    finalPrice = min(별지점_매수, 큰수)
    baseQty = floor(amt / finalPrice)
    주문: [LOC] finalPrice / baseQty주

# 대폭락 티어 (사다리) — baseQty 위에 추가
checkQty = baseQty + 1
for k in 1..15:
    tierPrice = amt / checkQty
    if 0 < tierPrice < 큰수:
        주문 += [추가] tierPrice 이하 / +1주
        tierFound++
    if tierFound >= 5: break
    checkQty++
```
**사다리 단가 = `amt/(baseQty+k)`**, 큰수 미만만, 최대 5단. ← §14 미해결 해소.

## 3. 매도 주문 생성

```
qQty      = floor(shares × 0.25)        # 쿼터 물량
revSellQty = floor(shares / (n/2))      # 리버스 등분 물량

if mode==REVERSE:
    if prevMode==NORMAL: 매도1 = [MOC] revSellQty주        # 리버스 1일차
    else:                매도1 = [LOC] sma5 / revSellQty주  # 리버스 2일차+
    매도2 = -
else:                                                       # 일반
    매도1 = [LOC] 별지점_매도 / qQty주                      # 쿼터매도
    매도2 = [지정가] 지정가_매도 / (shares − qQty)주        # 나머지 3/4
```

## 4. T값 갱신 (다음날, 보유수량 변화로 역추론)

action = (newShares < oldShares) ? SELL : (newShares > oldShares) ? BUY : NONE

```
BUY & NORMAL:
    oldShares==0     → T += 1
    T < n/2          → close>avg ? T+=0.5 : T+=1
    T >= n/2(후반전) → T += 1
BUY & REVERSE:       → T += (n − T) × 0.25

SELL 일반쿼터(상황3):
    NORMAL  → T = oldT × 0.75
    REVERSE → T = oldT × (1 − 2/n)
SELL 100%(상황1, newShares≤0): 사이클 종료, T = 0
SELL 상황2 (newShares ≤ oldShares×0.60):   # 지정가 3/4 체결 + 같은날 재매수 가능
    newShares > qQty:  close>avg ? T=oldT×0.25+0.5 : T=oldT×0.25+1.0
    else:              T = oldT × 0.25
```

## 5. 모드 전환
```
isCycleEnd = (newShares<=0 && action==SELL) → mode=CYCLE_END, T=0
NORMAL → REVERSE : T >= n−1
REVERSE → NORMAL : close > avg × (1 − targetYield/100)
```

## 6. 잔금 / 손익 (복리)
```
todayProfit:
  상황1(100%): qQty×(close−avg) + (old−qQty)×(지정가_매도−avg)
  상황2:        (old−qQty)×(지정가_매도−avg)
  상황3(쿼터):  soldQty×(close−avg)
balance = principal − shares×avg + Σ(DB 실현손익) + todayProfit
```
→ 실현손익을 잔금에 누적 = **복리**가 기본. (단리로 바꾸려면 Σ실현손익 항 제거)

중간진입 시 T 역산: `T = (shares×avg / principal) × n`.

## 7. 라오어 원문 대비 차이 (요약)
1. 별% = 목표수익률×(1−2T/n) — 목표수익률 커스텀(원문은 15/20 고정표의 일반화).
2. 큰수 = **종가**×(1+10%) 이며 매수가 **상한**으로 작동 (원문은 평단 기준 큰수).
3. 리버스 기준선 = **5일평균(sma5)** (원문은 별지점). 리버스에선 P=0.
4. 리버스 T 갱신: 매수 +=(n−T)×0.25, 쿼터매도 ×(1−2/n) (원문 미명시 → 언이 해석).
5. 잔금에 실현손익 누적 = 복리 기본.
6. 모든 수량 floor.

## 8. 백테스터 설계 함의
- 이 스크립트는 **시뮬레이터가 아니라 일지+주문생성기**. 매일 사용자가 *실제 체결된* 보유·평단을 입력하면 DB 직전값과 비교해 행동 역추론.
- 백테스터는 이 "역추론" 대신 **OHLC로 LOC/MOC/지정가 자동 체결 → 보유·평단·실현손익 갱신**을 직접 시뮬레이션해야 함. 주문생성·T갱신·모드·P·사다리 공식은 위를 그대로 차용.
- 검증: 같은 입력 시퀀스를 이 시트와 백테스터에 넣어 DB 행이 일치하는지 대조(골든 테스트).
