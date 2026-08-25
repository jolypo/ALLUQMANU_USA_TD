from __future__ import annotations
import os,tempfile,uuid
from telegram import Bot,Update
from telegram.ext import Application,CommandHandler
from app.config import settings
from app.telegram.messages import signal_text
from app.reports.card import option_card
from app.reports.performance import performance


class TelegramHub:
    def __init__(self,service,open_repo,history_repo,state_repo):
        self.service=service; self.open_repo=open_repo; self.history_repo=history_repo; self.state_repo=state_repo
        self.app=Application.builder().token(settings.signal_bot_token).updater(None).build()
        self.profit=Bot(settings.profit_bot_token); self.report=Bot(settings.report_bot_token)
        handlers={"start":self.start,"help":self.help,"myid":self.myid,"stock":self.stock,"option":self.option,"indexoption":self.indexoption,"open":self.open_trades,"status":self.status,"health":self.status,"risk":self.risk,"performance":self.performance,"report":self.report_cmd,"settings":self.settings_cmd,"pause":self.pause,"resume":self.resume,"market":self.market}
        for cmd,fn in handlers.items(): self.app.add_handler(CommandHandler(cmd,fn))

    def allowed(self,u:Update)->bool: return bool(u.effective_user and u.effective_user.id==settings.telegram_admin_user_id)
    async def _deny(self,u): await u.effective_message.reply_text("⛔ غير مصرح لهذا الحساب.")
    def _paused(self)->bool:
        rows=self.state_repo.all(); return bool(rows and rows[0].get("paused"))
    def _set_paused(self,v:bool): self.state_repo.replace([{"paused":v}])

    def _portfolio_gate(self,d:dict)->tuple[bool,str]:
        rows=[x for x in self.open_repo.all() if x.get("status")=="OPEN"]
        if len(rows)>=settings.max_open_trades: return False,"تم بلوغ الحد الأقصى للصفقات المفتوحة"
        total=sum(float(x.get("risk_pct",0) or 0) for x in rows)
        if total+float(d.get("risk_pct",0) or 0)>settings.max_total_open_risk: return False,"إجمالي المخاطر المفتوحة سيتجاوز الحد المسموح"
        if any(x.get("symbol")==d.get("symbol") for x in rows): return False,"يوجد بالفعل Trade مفتوح على الأصل نفسه"
        sector=d.get("sector")
        same=sum(1 for x in rows if sector not in {None,"N/A","INDEX"} and x.get("sector")==sector)
        if same>=2: return False,f"التعرض الحالي لقطاع {sector} مرتفع"
        return True,"ACCEPT"

    async def start(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        await u.effective_message.reply_text("✅ نظام ALLUQMANU_USA_TD جاهز.\n\n/stock /option /indexoption\n/open /performance /report /market /status /health /settings /risk /pause /resume /myid")
    async def help(self,u,c): return await self.start(u,c)
    async def myid(self,u,c): await u.effective_message.reply_text(f"👤 Telegram User ID:\n{u.effective_user.id}")

    async def _run(self,u,kind):
        if not self.allowed(u): return await self._deny(u)
        if self._paused(): return await u.effective_message.reply_text("⏸️ البحث عن إشارات جديدة موقوف. استخدم /resume.")
        is_open,clock=await self.service.market_is_open()
        if not is_open: return await u.effective_message.reply_text(f"⏰ السوق الأمريكي مغلق أو تعذر تأكيد أنه مفتوح.\nلن يتم استهلاك الفحص خارج الجلسة.\n{clock}")
        await u.effective_message.reply_text("🔎 بدأ الفحص اليدوي... لا يتم إنشاء إشارات تلقائيًا.")
        fn={"stock":self.service.best_stock,"option":self.service.best_equity_option,"index":self.service.best_index_option}[kind]
        s,rejects=await fn()
        if not s:
            msg="❌ لا توجد صفقة READY حاليًا."
            if rejects: msg += "\n\nأسباب مختصرة:\n"+"\n".join(f"• {x}" for x in rejects[-5:])
            return await u.effective_message.reply_text(msg)
        d=s.to_dict(); d["trade_id"]=("OPT" if d.get("option") else "STK")+"-"+uuid.uuid4().hex[:8].upper(); d["status"]="OPEN"; d.update({"tp1_hit":False,"tp2_hit":False,"tp3_hit":False,"near_stop_sent":False})
        ok,reason=self._portfolio_gate(d)
        if not ok: return await u.effective_message.reply_text(f"❌ تم رفض فتح Paper Trade بعد التحليل.\nالسبب: {reason}")
        self.open_repo.append(d); text=signal_text(d)
        if settings.telegram_channel_chat_id:
            if d.get("option"):
                path=os.path.join(tempfile.gettempdir(),f'{d["trade_id"]}.png'); option_card(d,path)
                with open(path,"rb") as f: await self.app.bot.send_photo(settings.telegram_channel_chat_id,photo=f,caption=f'🚨 {d["symbol"]} | {d["option"]["type"]} | Strike {d["option"]["strike"]}\nالتفاصيل في الرسالة التالية.')
                await self.app.bot.send_message(settings.telegram_channel_chat_id,text=text)
                try: os.remove(path)
                except OSError: pass
            else: await self.app.bot.send_message(settings.telegram_channel_chat_id,text=text)
            await u.effective_message.reply_text("✅ تم نشر الإشارة في القناة.")
        else:
            await u.effective_message.reply_text(text+"\n\n⚠️ TELEGRAM_CHANNEL_CHAT_ID غير مضبوط؛ لذلك لم تُنشر في القناة.")

    async def stock(self,u,c): await self._run(u,"stock")
    async def option(self,u,c): await self._run(u,"option")
    async def indexoption(self,u,c): await self._run(u,"index")

    async def open_trades(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        rows=[x for x in self.open_repo.all() if x.get("status")=="OPEN"]
        if not rows: return await u.effective_message.reply_text("📂 لا توجد صفقات مفتوحة.")
        await u.effective_message.reply_text("📂 الصفقات المفتوحة\n\n"+"\n".join(f'• {x["symbol"]} | {x["trade_type"]} | Score {x["score"]} | {x.get("last_price","-")}' for x in rows))

    async def status(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        try: is_open,stamp=await self.service.market_is_open()
        except Exception: is_open,stamp=False,"N/A"
        await u.effective_message.reply_text(f"🤖 RUNNING ✅\nPaper: {settings.paper_mode}\nLive: {settings.live_trading}\nPaused: {self._paused()}\nUS Market open: {is_open}\nStocks: {len(settings.stocks)}\nIndex: {','.join(settings.indices)}\n0DTE: OFF\nChannel ID: {'SET' if settings.telegram_channel_chat_id else 'PENDING'}")

    async def risk(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        rows=[x for x in self.open_repo.all() if x.get("status")=="OPEN"]
        total=sum(float(x.get("risk_pct",0) or 0) for x in rows)
        await u.effective_message.reply_text(f"🛡️ المخاطر\nMax/trade: {settings.max_risk_per_trade*100:.2f}%\nMax total: {settings.max_total_open_risk*100:.2f}%\nOpen risk: {total*100:.2f}%\nMax open: {settings.max_open_trades}\nMIN R/R: 1:{settings.min_rr}\nرأس المال: غير محدد؛ لذلك لا يوجد Position Size بالدولار.")

    async def performance(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        p=performance(self.history_repo.all())
        await u.effective_message.reply_text(f'📊 الأداء الورقي\nالصفقات: {p["trades"]}\nالفوز: {p["wins"]}\nالخسارة: {p["losses"]}\nWin Rate: {p["win_rate"]}%\nProfit Factor: {p["profit_factor"]}\nNet P&L: {p["net_pnl_pct"]}%')

    async def report_cmd(self,u,c): return await self.performance(u,c)
    async def settings_cmd(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        await u.effective_message.reply_text(f"⚙️ الإعدادات\nStock feed: {settings.alpaca_stock_feed}\nOptions feed: {settings.alpaca_options_feed}\nMin Score: {settings.min_score}\nMin R/R: {settings.min_rr}\nWatermark: {settings.watermark_name}\n0DTE: OFF")
    async def pause(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        self._set_paused(True); await u.effective_message.reply_text("⏸️ تم إيقاف إنشاء الإشارات اليدوية. متابعة الصفقات تبقى فعالة.")
    async def resume(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        self._set_paused(False); await u.effective_message.reply_text("▶️ تم استئناف البحث اليدوي عن الإشارات.")
    async def market(self,u,c):
        if not self.allowed(u): return await self._deny(u)
        from app.market.regime import MarketRegimeEngine
        reg=await MarketRegimeEngine(self.service.provider).get(); op,stamp=await self.service.market_is_open()
        await u.effective_message.reply_text(f"🌎 Market Regime: {reg}\nUS Market Open: {op}\nالمرجع الأساسي: SPY / IEX")
