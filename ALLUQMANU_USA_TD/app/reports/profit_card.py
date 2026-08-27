from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont
from app.config import settings


def _font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()


def profit_update_card(trade: dict, profit_usd: float, profit_sar: float, current_price: float, output_path: str):
    # User-requested tiers: <100 green, 100..<300 yellow, >=300 blue.
    if profit_usd >= 300:
        bg = (22, 74, 135); accent = (115, 190, 255)
    elif profit_usd >= 100:
        bg = (110, 82, 8); accent = (255, 215, 70)
    else:
        bg = (16, 92, 56); accent = (90, 230, 145)
    img = Image.new("RGB", (1200, 620), bg)
    d = ImageDraw.Draw(img)
    title = _font(42, True); big = _font(96, True); mid = _font(34, True); small = _font(24)
    option = trade.get("option") or {}
    label = f"{trade.get('symbol','')} {option.get('strike','')} {option.get('type','')}".strip()
    d.text((60, 45), "PROFIT UPDATE", font=title, fill=(255,255,255))
    d.text((60, 115), label, font=mid, fill=accent)
    d.text((60, 205), f"+${profit_usd:,.2f}", font=big, fill=(255,255,255))
    d.text((65, 325), f"+{profit_sar:,.2f} SAR", font=mid, fill=accent)
    d.text((65, 395), f"Contract: ${current_price:.2f}", font=mid, fill=(255,255,255))
    d.text((65, 470), str(trade.get("trade_id", "")), font=small, fill=(235,235,235))
    d.text((65, 545), settings.watermark_name, font=small, fill=(235,235,235))
    img.save(output_path, "PNG")
