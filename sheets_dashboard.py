"""Google Sheet 대시보드 — 진행상황 친절 표시 + 서식(색·폰트·병합) + 일별 기록."""
import datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MODE_KR = {
    "NORMAL": "🟢 일반모드 (분할매수 + 익절)",
    "REVERSE": "🔴 리버스모드 (소진 · 손절 정리)",
    "CYCLE_END": "🎉 사이클 종료 (재시작)",
}

# 색 (0~1)
NAVY = {"red": 0.13, "green": 0.16, "blue": 0.30}
TEAL = {"red": 0.18, "green": 0.36, "blue": 0.44}
GRAY = {"red": 0.90, "green": 0.91, "blue": 0.94}
GREENBG = {"red": 0.84, "green": 0.93, "blue": 0.84}
REDBG = {"red": 0.97, "green": 0.83, "blue": 0.83}
GREEN_TX = {"red": 0.0, "green": 0.50, "blue": 0.0}
RED_TX = {"red": 0.80, "green": 0.0, "blue": 0.0}
WHITE = {"red": 1, "green": 1, "blue": 1}


def connect(sa_source, sheet_id):
    """sa_source = 파일경로 | JSON 문자열 | dict. (GitHub Secret은 JSON 문자열로 들어옴)"""
    import json, os
    if isinstance(sa_source, dict):
        creds = Credentials.from_service_account_info(sa_source, scopes=SCOPES)
    elif isinstance(sa_source, str) and sa_source.strip().startswith("{"):
        creds = Credentials.from_service_account_info(json.loads(sa_source), scopes=SCOPES)
    elif isinstance(sa_source, str) and os.path.exists(sa_source):
        creds = Credentials.from_service_account_file(sa_source, scopes=SCOPES)
    else:
        raise ValueError("서비스계정 자격증명을 찾을 수 없음 (경로/JSON 모두 아님)")
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)


# ----------------------------------------------------------------------
# 상태 저장 (GitHub Actions 러너는 매번 새 컨테이너 → 시트에 상태 영속화)
# ----------------------------------------------------------------------
_STATE_HEADER = ["ticker", "shares", "avg", "T", "mode", "prev_mode",
                 "realized_cum", "cycles", "last_run"]


def load_states(ss):
    """{ticker: (dict_state, last_run)} 반환. 없으면 빈 dict."""
    ws = _ws(ss, "_상태", rows=20, cols=10)
    vals = ws.get_all_values()
    out = {}
    if not vals or vals[0] != _STATE_HEADER:
        return out
    for row in vals[1:]:
        if not row or not row[0]:
            continue
        d = dict(zip(_STATE_HEADER, row))
        out[d["ticker"]] = (
            {"shares": int(float(d["shares"] or 0)), "avg": float(d["avg"] or 0),
             "T": float(d["T"] or 0), "mode": d["mode"] or "NORMAL",
             "prev_mode": d["prev_mode"] or "NORMAL",
             "realized_cum": float(d["realized_cum"] or 0), "cycles": int(float(d["cycles"] or 0))},
            d["last_run"] or None,
        )
    return out


def save_states(ss, states):
    """states = {ticker: (state_obj_or_dict, last_run)}. 전체 덮어씀."""
    ws = _ws(ss, "_상태", rows=20, cols=10)
    rows = [_STATE_HEADER]
    for tk, (s, last_run) in states.items():
        g = (lambda k: getattr(s, k) if hasattr(s, k) else s[k])
        rows.append([tk, g("shares"), round(g("avg"), 4), round(g("T"), 6),
                     g("mode"), g("prev_mode"), round(g("realized_cum"), 4),
                     g("cycles"), last_run or ""])
    ws.clear()
    ws.update(range_name="A1", values=rows)


def _ws(ss, title, rows=300, cols=8):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)


def _progress_bar(frac, width=20):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled) + f"  {frac*100:.0f}%"


def _orders_text(orders):
    lines = []
    for kind, price, qty in orders:
        if kind == "BUY":
            lines.append(f"  🔵 매수 LOC   ${price:.2f} 이하 / {qty}주")
        elif kind == "SELL_LOC":
            lines.append(f"  🔴 매도 LOC   ${price:.2f} / {qty}주  (쿼터)")
        elif kind == "SELL_LIMIT":
            lines.append(f"  🔴 매도 지정가 ${price:.2f} / {qty}주")
        elif kind == "SELL_MOC":
            lines.append(f"  🔴 매도 MOC   시장가 / {qty}주  (리버스 1일차)")
    return "\n".join(lines) if lines else "  (오늘 낼 주문 없음)"


def update_dashboard(ss, account, views, now=None):
    now = now or dt.datetime.now()
    ws = _ws(ss, "대시보드")
    sid = ws.id
    ws.clear()

    rows, merges, fmts = [], [], []

    def add(row):
        rows.append(row + [""] * (5 - len(row)))
        return len(rows)  # 1-based row number

    def band(r0, r1=None):  # 0-based half-open merge across A:E
        r1 = r1 or r0
        merges.append((r0 - 1, r1, 0, 5))

    def fmt(a1, f):
        fmts.append({"range": a1, "format": f})

    # ---- 타이틀 ----
    r = add(["♾️  무한매수법 V4.0  —  자동매매 대시보드"]); band(r)
    fmt(f"A{r}:E{r}", {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                       "textFormat": {"bold": True, "fontSize": 16, "foregroundColor": WHITE}})
    r = add([f"⏱  업데이트  {now:%Y-%m-%d %H:%M:%S}"]); band(r)
    fmt(f"A{r}:E{r}", {"backgroundColor": GRAY, "horizontalAlignment": "CENTER",
                       "textFormat": {"italic": True, "fontSize": 9}})
    add([])

    # ---- 계좌 요약 ----
    # 전략 손익 = 종목별 (실현누적 + 미실현) 합. 계좌 equity 와 다름(paper 계좌는 더 큼).
    strat_principal = sum(v["principal"] for v in views)
    strat_pnl = sum(v["realized_cum"] + v["unrealized"] for v in views)
    strat_pct = (strat_pnl / strat_principal * 100) if strat_principal else 0.0
    daily = account["equity"] - account["last_equity"]
    r = add(["📊  계좌 요약"]); band(r)
    fmt(f"A{r}:E{r}", {"backgroundColor": TEAL,
                       "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE}})
    r = add(["계좌 평가금(Alpaca)", f"${account['equity']:,.2f}", "현금", f"${account['cash']:,.2f}"])
    fmt(f"A{r}:A{r}", {"textFormat": {"bold": True}})
    add(["매수가능 (BP)", f"${account['buying_power']:,.2f}", "전일대비(계좌)", f"${daily:+,.2f}"])
    r = add(["전략 투입원금", f"${strat_principal:,.0f}", "전략 손익(실현+미실현)",
             f"${strat_pnl:+,.2f}  ({strat_pct:+.1f}%)"])
    fmt(f"A{r}:A{r}", {"textFormat": {"bold": True}})
    fmt(f"D{r}", {"textFormat": {"foregroundColor": GREEN_TX if strat_pnl >= 0 else RED_TX, "bold": True}})
    add([])

    # ---- 종목별 ----
    for v in views:
        prog = v["T"] / v["n"]
        half = "전반전" if v["T"] < v["n"] / 2 else "후반전"
        un = v["unrealized"]

        r = add([f"📈  {v['ticker']}"]); band(r)
        fmt(f"A{r}:E{r}", {"backgroundColor": TEAL,
                           "textFormat": {"bold": True, "fontSize": 12, "foregroundColor": WHITE}})

        r = add(["모드", MODE_KR.get(v["mode"], v["mode"])])
        fmt(f"A{r}:A{r}", {"textFormat": {"bold": True}})
        fmt(f"B{r}:B{r}", {"backgroundColor": REDBG if v["mode"] == "REVERSE" else GREENBG,
                           "textFormat": {"bold": True}})

        r = add(["진행 (T / 분할)", f"{v['T']:.3f} / {v['n']}   ({half})", "진행률", _progress_bar(prog)])
        fmt(f"D{r}", {"textFormat": {"fontFamily": "Consolas"}})
        add(["보유수량", f"{v['shares']}주", "평단가", f"${v['avg']:.2f}"])

        r = add(["평가금액", f"${v['position_value']:,.2f}", "평가손익",
                 f"${un:+,.2f}  ({v['unrealized_pct']:+.1f}%)"])
        fmt(f"D{r}", {"textFormat": {"foregroundColor": GREEN_TX if un >= 0 else RED_TX, "bold": True}})

        r = add(["누적 실현손익", f"${v['realized_cum']:+,.2f}", "완료 사이클", f"{v['cycles']}회"])
        fmt(f"B{r}", {"textFormat": {"foregroundColor": GREEN_TX if v["realized_cum"] >= 0 else RED_TX, "bold": True}})

        add(["별지점 (매도기준)", f"${v['star_sell']:.2f}", "큰수 (매수상한)", f"${v['large']:.2f}"])
        add(["오늘 1회 매수금", f"${v['amt']:,.2f}", "기준종가", f"${v['ref_close']:.2f}"])

        r = add(["▶  오늘 낼 주문"]); band(r)
        fmt(f"A{r}:E{r}", {"backgroundColor": GRAY, "textFormat": {"bold": True}})
        r = add([_orders_text(v["orders_text"])]); band(r)
        fmt(f"A{r}:E{r}", {"wrapStrategy": "WRAP", "verticalAlignment": "TOP",
                           "textFormat": {"fontFamily": "Consolas", "fontSize": 10}})
        add([])

    r = add(["ℹ️  일반모드 = 평단 위에서 분할 익절 / 리버스 = 원금 소진 후 손절 정리.  "
             "별지점 위면 매도, 아래면 매수.  큰수 = 매수가 상한선."]); band(r)
    fmt(f"A{r}:E{r}", {"backgroundColor": GRAY, "wrapStrategy": "WRAP",
                       "textFormat": {"italic": True, "fontSize": 9}})

    # ---- 쓰기 ----
    ws.update(range_name="A1", values=rows)

    # ---- 구조 서식 (병합·열너비·고정) ----
    widths = [210, 180, 150, 230, 40]
    requests = [{"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 2}},
        "fields": "gridProperties.frozenRowCount"}}]
    for i, w in enumerate(widths):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    for r0, r1, c0, c1 in merges:
        requests.append({"mergeCells": {"range": {
            "sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}, "mergeType": "MERGE_ALL"}})
    ss.batch_update({"requests": requests})

    # ---- 셀 서식 ----
    if fmts:
        ws.batch_format(fmts)


def append_history(ss, history_rows):
    ws = _ws(ss, "기록")
    header = ["일시", "종목", "모드", "T", "종가", "보유", "평단", "평가손익",
              "실현누적", "사이클", "행동", "비고"]
    existing = ws.get_all_values()
    if not existing:
        ws.update(range_name="A1", values=[header])
        ws.format("A1:L1", {"backgroundColor": TEAL, "textFormat": {"bold": True, "foregroundColor": WHITE}})
        ws.freeze(rows=1)
    ws.append_rows(history_rows, value_input_option="USER_ENTERED")
