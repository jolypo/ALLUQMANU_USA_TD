from PIL import Image,ImageDraw,ImageFont
from app.config import settings


def _font(size:int,bold=False):
    candidates=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in candidates:
        try:return ImageFont.truetype(p,size)
        except: pass
    return ImageFont.load_default()


def option_card(signal: dict, path: str):
    o=signal["option"]
    im=Image.new("RGB",(1600,900),(7,16,20)); d=ImageDraw.Draw(im)
    d.rounded_rectangle((70,70,1530,250),30,outline=(197,155,53),width=3)
    d.text((130,115),"OPTIONS PAPER SIGNAL",font=_font(58,True),fill=(235,190,55))
    d.text((1110,125),settings.watermark_name,font=_font(34,True),fill=(90,100,105))
    d.rounded_rectangle((70,290,1530,720),30,outline=(55,175,95),width=3)
    d.text((120,340),signal["symbol"],font=_font(95,True),fill=(120,220,70))
    d.text((120,470),f'{o["type"]}  |  STRIKE {o["strike"]}',font=_font(52,True),fill=(235,235,235))
    d.text((120,570),f'ENTRY ${o["entry_low"]:.2f} - ${o["entry_high"]:.2f}',font=_font(48,True),fill=(120,220,70))
    d.text((850,390),f'EXPIRY  {o["expiration"]}',font=_font(44,True),fill=(235,235,235))
    d.text((850,490),f'DTE  {o["dte"]}',font=_font(44,True),fill=(235,235,235))
    d.text((850,590),f'{signal["trade_type"]}',font=_font(32,True),fill=(190,190,190))
    d.text((105,785),"Full contract details in Telegram message",font=_font(35),fill=(220,175,65))
    d.text((1180,785),settings.watermark_name,font=_font(34,True),fill=(55,65,70))
    im.save(path,quality=92)
