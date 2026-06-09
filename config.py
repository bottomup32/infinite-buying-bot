"""봇 설정. 종목별 파라미터 + 전역 옵션. 비밀값은 .env 에서."""
import os
from dotenv import load_dotenv
import strategy as st

load_dotenv()

# ----- Alpaca -----
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# ----- Google Sheet -----
GOOGLE_SA_JSON = os.getenv("GOOGLE_SA_JSON", "")
DASHBOARD_SHEET_ID = os.getenv("DASHBOARD_SHEET_ID", "")

# ----- 상태 저장 디렉토리 -----
STATE_DIR = os.path.join(os.path.dirname(__file__), "state")

# ----------------------------------------------------------------------
# 종목별 전략 설정 (여기를 수정해서 운용 조정)
#   variant: 'uni'(언이 복리) | 'laoer'(라오어 단리)
#   원하면 base_yield_pct(목표수익률)·n(분할)·principal 조정
# ----------------------------------------------------------------------
def _params(ticker, variant, principal, n=40, base_yield_pct=None):
    if variant == "laoer":
        p = st.laoer_params(ticker, n=n, principal=principal)
        if base_yield_pct is not None:
            p.base_yield_pct = base_yield_pct
        return p
    by = base_yield_pct if base_yield_pct is not None else (15.0 if ticker == "TQQQ" else 20.0)
    return st.uni_params(ticker, n=n, principal=principal, base_yield_pct=by)


# 운용 종목 목록
#   계좌 $100,000 → 2종목 각 $50,000, 20분할(1회 매수금 ≈ $2,500/종목)
#   * 단일종목 원하면 한 줄 지우고 principal=100000 으로.
#   * 더 보수적으로 가려면 n=40 (1회 ≈ $1,250) 또는 variant="laoer"(단리).
PORTFOLIO = [
    _params("TQQQ", variant="uni", principal=50000.0, n=20),
    _params("SOXL", variant="uni", principal=50000.0, n=20),
]
