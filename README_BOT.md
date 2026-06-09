# 무한매수법 V4.0 봇 (Alpaca paper) — 셋업 가이드

## 구성
| 파일 | 역할 |
|---|---|
| `strategy.py` | 전략 순수 코어 (백테스트·봇 공용) |
| `broker_alpaca.py` | Alpaca 래퍼 (계좌·포지션·일봉·체결·주문) |
| `sheets_dashboard.py` | Google Sheet 대시보드 + 기록 |
| `bot.py` | 일일 실행 오케스트레이터 (기본 dry-run) |
| `config.py` | 종목별 설정 (PORTFOLIO 편집) |
| `backtest.py`,`scenarios.py` | 백테스트 |

## 1. 설치
```
pip install -r requirements.txt
```

## 2. 비밀값 설정
`.env.example` → `.env` 복사 후 채우기:
```
ALPACA_API_KEY=...          # Alpaca paper 키
ALPACA_SECRET_KEY=...
ALPACA_PAPER=true
GOOGLE_SA_JSON=./secrets/service_account.json
DASHBOARD_SHEET_ID=...      # 구글 스프레드시트 ID
```

## 3. 실행
```
python bot.py            # dry-run: 주문 계산·출력·대시보드만 (제출 안 함)
python bot.py --live     # 실제 주문 제출 (paper 계좌)
python bot.py --no-sheet # 구글시트 갱신 생략
```

## 4. 자동 스케줄 (중요: 미장 마감 전 실행)
- LOC/MOC 주문은 **미 동부시간 15:58 ET 이전** 제출돼야 종가 체결.
- 권장: **15:45 ET** 1회 실행 (서머타임 한국 04:45 / 비서머 05:45).
- Windows 작업 스케줄러:
  ```
  프로그램: python
  인수: "c:\Not_Onedrive_AI project\Infinite_inve\bot.py" --live
  트리거: 매일 04:45 (서머) — 거래일만
  ```

## 동작 원리 (라이브 = 언이 시트 실시간판)
1. 브로커에서 **실제 보유·평단·체결** 읽음 → 직전 저장상태와 비교해 T·모드·실현손익 갱신(`reconcile`).
2. `compute_orders`로 오늘 주문 계산 (전반/후반 매수 + 사다리, 쿼터/지정가 매도, 리버스 MOC).
3. `--live`면 기존 미체결 취소 후 제출.
4. Google Sheet **대시보드** + **기록** 갱신.

## 안전
- 기본 **dry-run**. `--live` 명시해야 제출.
- paper 계좌에서 충분히 검증 후 실계좌 고려.
- `.env`/`secrets/`/`state/`는 `.gitignore` 처리 — 외부 유출 금지.

## 한계 / TODO
- 매수 사다리 다수 LOC = Alpaca 매수가능액(BP) 예약으로 일부 거부 가능 → 실패는 로그로 표시, 다음날 재시도.
- 실현손익은 체결가−직전평단 근사. 부분체결 다수일 때 오차 가능.
- 골든테스트(언이 시트 DB 대조) 미수행.
- 슬리피지·수수료·세금·환율 미반영.
