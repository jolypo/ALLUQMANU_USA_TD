def performance(history:list[dict])->dict:
    closed=[x for x in history if x.get("status") in {"WIN","LOSS","BREAKEVEN","CLOSED"}]
    wins=[x for x in closed if x.get("status")=="WIN"]
    losses=[x for x in closed if x.get("status")=="LOSS"]
    pnl=[float(x.get("pnl_pct",0) or 0) for x in closed]
    gross_win=sum(x for x in pnl if x>0); gross_loss=abs(sum(x for x in pnl if x<0))
    return {
        "trades":len(closed),"wins":len(wins),"losses":len(losses),
        "win_rate":round(len(wins)/len(closed)*100,1) if closed else 0,
        "net_pnl_pct":round(sum(pnl),2),
        "profit_factor":round(gross_win/gross_loss,2) if gross_loss else (999.0 if gross_win else 0),
    }
