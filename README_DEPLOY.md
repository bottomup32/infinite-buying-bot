# GitHub Actions 자동 배포 가이드

PC 꺼도 매일 자동 실행 (GitHub 서버에서 cron). 무료.

## 동작
- 매일 미장 마감 ~20분 전 자동 실행 → 주문 제출 + Google Sheet 갱신.
- 상태(T·모드·실현손익)는 **Google Sheet `_상태` 탭**에 저장 → 러너 꺼져도 유지.
- DST는 cron 2개 + 장마감 가드로 자동 대응 (정확히 1회만 주문).

---

## 1단계 — GitHub 비공개 레포 생성
1. github.com → New repository
2. 이름 예: `infinite-buying-bot`, **Private** 선택, 나머지 빈칸(README 추가 X) → Create

## 2단계 — 코드 푸시 (이미 로컬 커밋됨)
레포 만들면 뜨는 URL로 아래 실행 (PowerShell, 프로젝트 폴더에서):
```
git remote add origin https://github.com/<너아이디>/infinite-buying-bot.git
git branch -M main
git push -u origin main
```
(로그인 창 뜨면 GitHub 계정으로 인증)

## 3단계 — Secrets 4개 등록
레포 → **Settings → Secrets and variables → Actions → New repository secret** 로 4개 추가:

| 이름 | 값 |
|---|---|
| `ALPACA_API_KEY` | Alpaca paper Key |
| `ALPACA_SECRET_KEY` | Alpaca paper Secret |
| `DASHBOARD_SHEET_ID` | 구글시트 ID (`17Iv4XZ2...`) |
| `GOOGLE_SA_JSON` | **`secrets/service_account.json` 파일 전체 내용 복붙** (`{`부터 `}`까지 전부) |

## 4단계 — 동작 확인
1. 레포 **Actions** 탭 → 워크플로 활성화(Enable) 클릭(처음 1회)
2. `infinite-buying-bot` 워크플로 → **Run workflow** → mode `dry` → 실행
3. 초록 체크 + Google Sheet 갱신되면 성공
4. 이후 **매일 자동**(평일) 실행됨. 실제 주문은 스케줄 실행에서 `--live`로 나감.

---

## 주의
- ⚠️ **Secrets는 레포에 코드로 올리지 말 것.** `.env`·`secrets/`는 `.gitignore`로 제외돼 있음. 값은 위 Secrets에만.
- GitHub 무료: 비공개 레포 Actions 월 2000분 — 1회 ~1분이라 충분.
- 스케줄 워크플로는 **레포 60일 무활동 시 자동 정지** → 가끔 커밋하거나 수동 실행으로 유지.
- cron은 부하 시 수 분 지연 가능. 마감 임박 가드(2~45분)가 잘못된 시각 제출을 막음. 너무 지연돼 15:58 ET 넘으면 그날 CLS 주문은 거부(로그 표시), 다음날 정상.
- 실거래 전 **paper로 충분히** 관찰. 대시보드/기록 탭으로 매일 확인.

## 자동 켜고 끄기
- 일시정지: Actions 탭 → 워크플로 → `···` → Disable workflow
- 재개: Enable workflow
