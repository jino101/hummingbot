def status_payload(config, risk, opportunities=None):
    opportunities = opportunities or []
    return {
        "mode": "LIVE" if config.live_enabled else "PAPER",
        "kill_switch": risk.kill_switch,
        "daily_trades": risk.daily_trades,
        "daily_pnl": risk.daily_pnl,
        "strategies": {
            "cross_exchange": True,
            "triangular": True,
            "solana_dex": True,
            "meme_discovery": config.dynamic_meme_discovery,
        },
        "venues": {
            "cex": config.cex,
            "solana_dex": config.solana_dex,
        },
        "opportunities": [o.__dict__ for o in opportunities[:50]],
    }
