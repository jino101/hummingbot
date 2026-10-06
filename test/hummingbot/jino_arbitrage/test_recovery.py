from hummingbot.jino_arbitrage.recovery import (
    LegStatus,
    RecoveryAction,
    decide_one_leg_recovery,
)


def test_both_filled_needs_no_recovery():
    decision = decide_one_leg_recovery(LegStatus.FILLED, LegStatus.FILLED)
    assert decision.action == RecoveryAction.NONE


def test_exposed_buy_leg_fails_closed_without_auto_hedge():
    decision = decide_one_leg_recovery(LegStatus.FILLED, LegStatus.FAILED)
    assert decision.action == RecoveryAction.MANUAL_INTERVENTION


def test_exposed_buy_leg_can_recommend_hedge_only_when_explicitly_enabled():
    decision = decide_one_leg_recovery(
        LegStatus.FILLED,
        LegStatus.FAILED,
        auto_hedge_enabled=True,
    )
    assert decision.action == RecoveryAction.HEDGE_BUY_LEG


def test_pending_opposite_leg_is_cancelled_after_failure():
    decision = decide_one_leg_recovery(LegStatus.PENDING, LegStatus.FAILED)
    assert decision.action == RecoveryAction.CANCEL_OPEN_LEG


def test_partial_fill_escalates_by_default():
    decision = decide_one_leg_recovery(LegStatus.PARTIAL, LegStatus.PENDING)
    assert decision.action == RecoveryAction.MANUAL_INTERVENTION
