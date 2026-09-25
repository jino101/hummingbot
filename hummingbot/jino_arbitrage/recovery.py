from dataclasses import dataclass
from enum import Enum


class LegStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecoveryAction(str, Enum):
    NONE = "none"
    WAIT = "wait"
    CANCEL_OPEN_LEG = "cancel_open_leg"
    HEDGE_BUY_LEG = "hedge_buy_leg"
    HEDGE_SELL_LEG = "hedge_sell_leg"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str


def decide_one_leg_recovery(
    buy_status: LegStatus,
    sell_status: LegStatus,
    auto_hedge_enabled: bool = False,
) -> RecoveryDecision:
    """Fail-safe decision helper for asymmetric arbitrage execution.

    The helper never places orders itself. It only maps observed leg states to
    a recovery recommendation. Automatic hedging must be explicitly enabled by
    the caller; otherwise any exposed filled/partial leg escalates to manual
    intervention.
    """
    if buy_status == LegStatus.FILLED and sell_status == LegStatus.FILLED:
        return RecoveryDecision(RecoveryAction.NONE, "both legs filled")

    terminal_bad = {LegStatus.FAILED, LegStatus.CANCELLED}
    exposed = {LegStatus.FILLED, LegStatus.PARTIAL}

    if buy_status in terminal_bad and sell_status in terminal_bad:
        return RecoveryDecision(RecoveryAction.NONE, "both legs ended without open exposure")

    if buy_status in exposed and sell_status in terminal_bad:
        if auto_hedge_enabled:
            return RecoveryDecision(
                RecoveryAction.HEDGE_BUY_LEG,
                "buy leg has exposure while sell leg failed or was cancelled",
            )
        return RecoveryDecision(
            RecoveryAction.MANUAL_INTERVENTION,
            "buy leg has exposure and automatic hedging is disabled",
        )

    if sell_status in exposed and buy_status in terminal_bad:
        if auto_hedge_enabled:
            return RecoveryDecision(
                RecoveryAction.HEDGE_SELL_LEG,
                "sell leg has exposure while buy leg failed or was cancelled",
            )
        return RecoveryDecision(
            RecoveryAction.MANUAL_INTERVENTION,
            "sell leg has exposure and automatic hedging is disabled",
        )

    if buy_status == LegStatus.PENDING and sell_status in terminal_bad:
        return RecoveryDecision(RecoveryAction.CANCEL_OPEN_LEG, "sell leg ended; cancel pending buy leg")
    if sell_status == LegStatus.PENDING and buy_status in terminal_bad:
        return RecoveryDecision(RecoveryAction.CANCEL_OPEN_LEG, "buy leg ended; cancel pending sell leg")

    if buy_status == LegStatus.PARTIAL or sell_status == LegStatus.PARTIAL:
        return RecoveryDecision(
            RecoveryAction.MANUAL_INTERVENTION,
            "partial fill requires explicit exposure handling",
        )

    return RecoveryDecision(RecoveryAction.WAIT, "execution is still in progress")
