"""Alpaca 브로커 래퍼 (paper). 계좌·포지션·일봉·체결·주문(LOC/MOC/지정가)."""
import datetime as dt

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest, MarketOrderRequest, GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


class Broker:
    def __init__(self, api_key, secret_key, paper=True):
        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.data = StockHistoricalDataClient(api_key, secret_key)

    # ---- 장 시간 ----
    def clock(self):
        c = self.trading.get_clock()
        mins = None
        try:
            mins = (c.next_close - c.timestamp).total_seconds() / 60.0
        except Exception:
            pass
        return {"is_open": bool(c.is_open), "next_close": c.next_close,
                "minutes_to_close": mins}

    # ---- 계좌 ----
    def account(self):
        a = self.trading.get_account()
        return {
            "equity": float(a.equity),
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "last_equity": float(a.last_equity),
        }

    # ---- 포지션 ----
    def position(self, symbol):
        """(qty:int, avg:float). 없으면 (0, 0.0)."""
        try:
            p = self.trading.get_open_position(symbol)
            return int(float(p.qty)), float(p.avg_entry_price)
        except Exception:
            return 0, 0.0

    # ---- 일봉 (전일 종가 + 5일평균용) ----
    def daily_closes(self, symbol, lookback_days=15):
        start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days + 10)
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start)
        bars = self.data.get_stock_bars(req)
        closes = [b.close for b in bars[symbol]]
        return closes  # 오름차순(과거→최신)

    def ref_close_and_sma5(self, symbol):
        closes = self.daily_closes(symbol)
        if not closes:
            return None, None
        ref_close = closes[-1]                       # 직전 거래일 종가
        last5 = closes[-5:] if len(closes) >= 5 else closes
        sma5 = sum(last5) / len(last5)
        return ref_close, sma5

    # ---- 체결 내역 (실현손익 계산용) ----
    def filled_orders_since(self, symbol, after_dt):
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after_dt,
                               symbols=[symbol], limit=200)
        orders = self.trading.get_orders(req)
        out = []
        for o in orders:
            fq = float(o.filled_qty or 0)
            if fq > 0 and o.filled_avg_price:
                out.append({
                    "side": "SELL" if o.side == OrderSide.SELL else "BUY",
                    "qty": fq, "price": float(o.filled_avg_price),
                })
        return out

    # ---- 주문 ----
    def cancel_open(self, symbol):
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol], limit=200)
        for o in self.trading.get_orders(req):
            try:
                self.trading.cancel_order_by_id(o.id)
            except Exception:
                pass

    def _side(self, s):
        return OrderSide.BUY if s == "BUY" else OrderSide.SELL

    def submit_loc(self, symbol, side, qty, limit_price):
        """LOC = 지정가 + 종가체결(TimeInForce.CLS)."""
        return self.trading.submit_order(LimitOrderRequest(
            symbol=symbol, qty=qty, side=self._side(side),
            time_in_force=TimeInForce.CLS, limit_price=round(float(limit_price), 2)))

    def submit_moc(self, symbol, side, qty):
        """MOC = 시장가 + 종가체결."""
        return self.trading.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=self._side(side),
            time_in_force=TimeInForce.CLS))

    def submit_limit_day(self, symbol, side, qty, limit_price):
        """지정가(장중) 매도 — 당일 유효."""
        return self.trading.submit_order(LimitOrderRequest(
            symbol=symbol, qty=qty, side=self._side(side),
            time_in_force=TimeInForce.DAY, limit_price=round(float(limit_price), 2)))
