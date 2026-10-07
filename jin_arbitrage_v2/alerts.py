import logging
log=logging.getLogger("jin_arbitrage_v2")
class AlertManager:
    def opportunity(self,op):
        log.info("OPPORTUNITY %s %s %.4f%%",op.strategy.value,op.symbol,op.net_pct)
    def risk_rejection(self,op,reason):
        log.warning("RISK_REJECT %s %s",op.symbol,reason)
    def execution_failure(self,op,error):
        log.error("EXECUTION_FAIL %s %s",op.symbol,error)
