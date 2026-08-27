from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont
from app.config import settings


def _font(size, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: return ImageFont.truetype(p, size)
    except OSError: return ImageFont.load_default()


def weekly_performance_card(report: dict, output_path: str):
    s = report.get("summary", {}); o = report.get("open_summary", {})
    img = Image.new("RGB", (1600, 850), (20,24,32)); d = ImageDraw.Draw(img)
    d.text((70,55), "WEEKLY PERFORMANCE", font=_font(54,True), fill=(245,245,245))
    rows = [
        ("Closed Trades", s.get("trades",0)), ("Wins", s.get("wins",0)), ("Losses", s.get("losses",0)),
        ("Win Rate", f"{s.get('win_rate',0)}%"), ("Profit Factor", s.get("profit_factor",0)),
        ("Net Realized", f"{float(s.get('net_pnl_pct',0)):+.2f}%"), ("Max Drawdown", f"{float(s.get('max_drawdown_pct',0)):+.2f}%"),
        ("Open Positions", o.get("total",0)), ("Unrealized", f"{float(o.get('unrealized_pnl_pct',0)):+.2f}%"),
    ]
    y=170
    for label, value in rows:
        d.text((90,y), label, font=_font(30), fill=(190,195,205)); d.text((700,y), str(value), font=_font(32,True), fill=(255,255,255)); y+=62
    d.text((90,780), settings.watermark_name, font=_font(24), fill=(150,155,165))
    img.save(output_path, "PNG")
