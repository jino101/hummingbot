import json, sqlite3, time

class TradeStore:
    def __init__(self,path="jin_arbitrage_v2.db"):
        self.db=sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS trades(
          id INTEGER PRIMARY KEY, ts REAL, strategy TEXT, symbol TEXT,
          buy_venue TEXT, sell_venue TEXT, net_pct REAL, size_usd REAL,
          pnl_usd REAL, state TEXT, metadata TEXT)""")
        self.db.commit()
    def record(self,op,state):
        self.db.execute("INSERT INTO trades(ts,strategy,symbol,buy_venue,sell_venue,net_pct,size_usd,pnl_usd,state,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (time.time(),op.strategy.value,op.symbol,op.buy_venue,op.sell_venue,op.net_pct,op.size_usd,op.estimated_profit_usd,str(state),json.dumps(op.metadata)))
        self.db.commit()
    def summary(self):
        row=self.db.execute("SELECT COUNT(*),COALESCE(SUM(pnl_usd),0),COALESCE(AVG(net_pct),0) FROM trades").fetchone()
        return {"trades":row[0],"pnl_usd":row[1],"avg_net_pct":row[2]}
