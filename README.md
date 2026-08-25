# ALLUQMANU_USA_TD

نظام إشارات تداول ورقي للأسهم والخيارات الأمريكية عبر Telegram. لا ينفذ أي صفقة حقيقية.

## الأصول المعتمدة

Stocks: AMD, UBER, MSFT, MU, META, INTC, ORCL, RKLB, AMZN, AVGO, TSLA, IBM, AAPL, NVDA, SPCX

Index options: SPX فقط.

## أنواع التداول

- Stock Intraday
- Stock Swing
- Equity Options Intraday
- Equity Options Swing
- Index Options Intraday
- Index Options Swing
- 0DTE: غير مفعّل حاليًا

## البوتات

- Signal Bot: استقبال الأوامر وإرسال الإشارات/SL.
- Profit Bot: مخصص لتنبيهات الأرباح عند اكتمال TradeMonitor المتقدم.
- Report Bot: مخصص للتقارير.

V1 تبقي منطق القرار خارج البوتات نفسها.

## الأوامر

`/start` `/help` `/stock` `/option` `/indexoption` `/open` `/status` `/health` `/risk` `/myid`

لا توجد إشارات تلقائية. البحث عن صفقة جديدة يحدث فقط عند `/stock` أو `/option` أو `/indexoption`. الـScheduler لا يملك مسارًا لإنشاء صفقة جديدة.

## البيانات

- Stock bars: Alpaca Market Data / IEX في الخطة المجانية.
- Options: Alpaca Indicative feed في الخطة المجانية، وليست OPRA Real-Time.
- SPX: التحليل الاتجاهي يستخدم SPY proxy، ثم يحاول جلب Option Chain الحقيقي لـSPX. إذا لم يكن متاحًا على الحساب/الخطة، يعيد النظام NO TRADE بدل اختلاق عقد.

## الاحتمالية

Score ليس Probability. حتى بلوغ `PROBABILITY_MIN_SAMPLES` تبقى الرسالة `UNVALIDATED` ولا يعرض النظام نسبة نجاح مختلقة.

## التخزين

V1 يستخدم JSON من خلال Repository abstraction. ملاحظة: filesystem المحلي في Render Free ليس تخزينًا دائمًا موثوقًا بعد restart/redeploy. يمكن استبدال Repository لاحقًا بـPostgreSQL.

## تشغيل محلي

1. انسخ `.env.example` إلى `.env`.
2. ضع أسرارك محليًا فقط.
3. ثبّت المتطلبات:

```bash
pip install -r requirements.txt
```

4. شغّل:

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

## Render

1. ارفع المشروع إلى GitHub بدون `.env`.
2. New Web Service في Render.
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. أضف Environment Variables من `.env.example`.
6. اضبط `PUBLIC_BASE_URL=https://YOUR-SERVICE.onrender.com`.
7. اترك `TELEGRAM_CHANNEL_CHAT_ID` فارغًا الآن إذا لم تعرفه؛ يمكن إضافته لاحقًا بدون تعديل الكود.
8. Health check: `/health`.

خدمة keep-alive خارجية يمكنها طلب `/health` كل 5 دقائق، لكن هذا لا يحول Render Free إلى بنية Production دائمة.

## Webhook

عند وجود `PUBLIC_BASE_URL`، التطبيق يضبط Webhook تلقائيًا للـSignal Bot على `/telegram/webhook`. يمكن وضع `TELEGRAM_WEBHOOK_SECRET` لتفعيل تحقق header من Telegram.

## صورة Options

يولد النظام بطاقة أفقية تلقائيًا تحتوي فقط على: اسم الأصل، CALL/PUT، Strike، نطاق الدخول، Expiration، DTE، نوع التداول، وعلامة مائية `ALLUQMANU_USA_TD`. التفاصيل الكاملة تبقى في رسالة Telegram.

## Security

- لا توجد أسرار في Source Code.
- `.env` مستبعد من Git.
- لا ترفع API keys أو Telegram tokens إلى GitHub.
- `LIVE_TRADING=false` ولا يوجد Live execution في V1.

## حدود V1 المهمة

هذه النسخة Production-Quality من ناحية الهيكل والـPaper Research، لكنها ليست Real-money-ready. لا تزال تحتاج تاريخ صفقات كافٍ، Backtesting/Walk-forward أوسع، تخزين دائم، وتحسين TradeMonitor قبل أي استخدام حقيقي.

## مراجعة ما قبل النشر

تمت مراجعة النسخة الحالية قبل التسليم وتشمل الإصلاحات التالية:

- يدعم LONG وSHORT للأسهم، ويحوّل الاتجاه الهابط إلى PUT عند اختيار عقد Option.
- يفصل اتجاه الأصل عن اتجاه Premium؛ شراء PUT يبقى مركز Option طويل وتتم مراقبة ربح العقد بصورة صحيحة.
- يفحص Intraday وSwing بصورة مستقلة ويختار الأفضل بدل تفضيل Swing آليًا.
- يمنع الفحص اليدوي خارج ساعات السوق افتراضيًا عبر Alpaca market clock (`ALLOW_OFF_HOURS_SCAN=false`).
- يطبق Max Open Trades وMax Total Open Risk ومنع تكرار الأصل وفلتر تعرض قطاعي مبسط قبل فتح Paper Trade.
- Near Stop + نقل الوقف إلى Break Even بعد TP1 + Time Exit للصفقات Intraday عند إغلاق السوق.
- تقارير يومية وأسبوعية عند ضبط Channel Chat ID.
- Probability تحفظ الرقم الحقيقي فقط بعد اكتمال الحد الأدنى من العينات.
- صورة Option أفقية ديناميكية مع العلامة المائية.

مهم: الاختبارات المحلية هنا تغطي المنطق ولا تستبدل اختبار الاتصال الحقيقي بـAlpaca/Telegram بعد وضع Environment Variables على Render. بعد أول Deploy اختبر `/health` ثم `/status` ثم `/stock` أثناء جلسة السوق قبل الاعتماد على بقية الأوامر.
