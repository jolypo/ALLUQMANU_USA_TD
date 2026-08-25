from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.config import settings
from app.reports.performance import performance


class TradeMonitor:
    """Monitoring-only scheduler. It has no path to create new signals."""
    def __init__(self,open_repo,history_repo,state_repo,provider,signal_bot,profit_bot,report_bot,channel_id,interval:int=300):
        self.open_repo=open_repo; self.history_repo=history_repo; self.state_repo=state_repo; self.provider=provider
        self.signal_bot=signal_bot; self.profit_bot=profit_bot; self.report_bot=report_bot; self.channel_id=channel_id
        self.interval=interval; self._task=None; self._last_daily=None; self._last_weekly=None

    async def _send(self,bot,text):
        if self.channel_id:
            try: await bot.send_message(self.channel_id,text)
            except Exception: pass

    async def _scheduled_reports(self):
        if not self.channel_id: return
        now=datetime.now(ZoneInfo("Asia/Riyadh"))
        p=performance(self.history_repo.all())
        if now.hour >= settings.report_hour_riyadh and self._last_daily != now.date():
            self._last_daily=now.date()
            await self._send(self.report_bot,f'📊 التقرير اليومي — Paper Trading\nالصفقات المغلقة: {p["trades"]}\nWin Rate: {p["win_rate"]}%\nProfit Factor: {p["profit_factor"]}\nNet P&L: {p["net_pnl_pct"]}%')
        # Friday evening Riyadh after the US Thursday/Friday week is substantially complete.
        if now.weekday()==4 and now.hour >= settings.report_hour_riyadh:
            key=f"{now.isocalendar().year}-{now.isocalendar().week}"
            if self._last_weekly != key:
                self._last_weekly=key
                await self._send(self.report_bot,f'📈 التقرير الأسبوعي — Paper Trading\nالصفقات المغلقة: {p["trades"]}\nالفوز: {p["wins"]}\nالخسارة: {p["losses"]}\nWin Rate: {p["win_rate"]}%\nProfit Factor: {p["profit_factor"]}\nNet P&L: {p["net_pnl_pct"]}%')

    async def cycle(self):
        rows=self.open_repo.all(); changed=False
        stocks=[x["symbol"] for x in rows if x.get("status")=="OPEN" and x.get("option") is None]
        stockbars={}
        try: stockbars=await self.provider.latest_bars(sorted(set(stocks)))
        except Exception: stockbars={}
        option_contracts=[x.get("option",{}).get("symbol") for x in rows if x.get("status")=="OPEN" and x.get("option")]
        option_contracts=[x for x in option_contracts if x]
        optquotes={}
        try: optquotes=await self.provider.option_quotes(option_contracts)
        except Exception: optquotes={}

        market_open=True
        try: market_open=bool((await self.provider.market_clock()).get("is_open"))
        except Exception: pass

        still=[]
        for t in rows:
            if t.get("status")!="OPEN": still.append(t); continue
            px=None
            if t.get("option"):
                q=optquotes.get(t["option"]["symbol"],{}) or {}
                bid=q.get("bp") or q.get("bid_price"); ask=q.get("ap") or q.get("ask_price")
                if bid and ask: px=(float(bid)+float(ask))/2
            else:
                b=stockbars.get(t["symbol"],{}) or {}
                if b.get("c") is not None: px=float(b["c"])
            if px is None: still.append(t); continue
            t["last_price"]=round(px,4); t["last_monitored_at"]=datetime.now(timezone.utc).isoformat()
            long=t.get("direction")=="LONG"
            entry=(float(t["entry_low"])+float(t["entry_high"]))/2
            stop=float(t["stop"])
            initial_risk=abs(entry-stop) or max(entry*.01,.01)

            # Intraday trades are never silently converted into swing positions.
            if "INTRADAY" in t.get("trade_type","") and not market_open:
                t["status"]="CLOSED"; t["exit_price"]=px; t["exit_reason"]="TIME_EXIT"
                t["pnl_pct"]=round(((px-entry)/entry*100)*(1 if long else -1),2)
                self.history_repo.append(t); changed=True
                await self._send(self.signal_bot,f'🟠 إغلاق زمني\n{t["symbol"]}\n🆔 {t.get("trade_id","Paper Trade")}\nالخروج الورقي: {px:.2f}\nالنتيجة: {t["pnl_pct"]:.2f}%')
                continue

            dist_to_stop=(px-stop) if long else (stop-px)
            if dist_to_stop <= initial_risk*settings.near_stop_fraction and dist_to_stop > 0 and not t.get("near_stop_sent"):
                t["near_stop_sent"]=True; changed=True
                await self._send(self.signal_bot,f'⚠️ Near Stop Loss\n{t["symbol"]}\nالسعر الورقي: {px:.2f}\nوقف الصفقة: {stop:.2f}')

            hit_sl = px <= stop if long else px >= stop
            if hit_sl:
                t["status"]="LOSS"; t["exit_price"]=px; t["exit_reason"]="STOP_LOSS"
                t["pnl_pct"]=round(((px-entry)/entry*100)*(1 if long else -1),2)
                self.history_repo.append(t); changed=True
                await self._send(self.signal_bot,f'🔴 وقف الخسارة\n{t["symbol"]}\n🆔 {t.get("trade_id","Paper Trade")}\nالخروج الورقي: {px:.2f}\nالنتيجة: {t["pnl_pct"]:.2f}%')
                continue

            for n in (1,2,3):
                key=f"tp{n}"; flag=f"tp{n}_hit"; target=float(t[key])
                hit=px>=target if long else px<=target
                if hit and not t.get(flag):
                    t[flag]=True; changed=True
                    await self._send(self.profit_bot,f'🟢 تحقق TP{n}\n{t["symbol"]}\nالسعر الورقي الحالي: {px:.2f}\nالهدف: {target:.2f}')
                    if n==1 and settings.trailing_after_tp1_to_entry:
                        t["stop"]=round(entry,4)
            if t.get("tp3_hit"):
                t["status"]="WIN"; t["exit_price"]=px; t["exit_reason"]="TP3"
                t["pnl_pct"]=round(((px-entry)/entry*100)*(1 if long else -1),2)
                self.history_repo.append(t); changed=True
                continue
            still.append(t)
        self.open_repo.replace(still if changed else rows)
        await self._scheduled_reports()

    async def loop(self):
        while True:
            try: await self.cycle()
            except Exception: pass
            await asyncio.sleep(self.interval)

    def start(self):
        if not self._task: self._task=asyncio.create_task(self.loop())
    async def stop(self):
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
