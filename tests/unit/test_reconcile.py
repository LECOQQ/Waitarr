from waitarr.core.model import Limits, TargetState
from waitarr.core.reconcile import (
    Action,
    Ownership,
    TargetRecord,
    reconcile,
    restore,
)

OFF = TargetState(False, Limits(0, 0))
SLOW = Limits(1024, 2048)
HELD = TargetState(True, SLOW)


def _step(
    record, observed, *, throttle, simulate=False, limits: Limits | None = SLOW
):
    return reconcile(
        record,
        observed,
        throttle=throttle,
        throttle_limits=limits,
        simulate=simulate,
    )


def test_idle_without_demand_does_nothing():
    step = _step(TargetRecord(), OFF, throttle=False)
    assert step.action is Action.NONE
    assert step.write is None


def test_first_playback_engages_and_remembers_the_state_found():
    step = _step(TargetRecord(), OFF, throttle=True)
    assert step.action is Action.ENGAGE
    assert step.write == HELD
    assert step.record == TargetRecord(
        Ownership.ENGAGED,
        before=OFF,
        applied=HELD,
        pending=HELD,
        pending_from=OFF,
    )


def test_engage_keeps_the_targets_own_limits_when_none_configured():
    own = TargetState(False, Limits(5000, 6000))
    step = _step(TargetRecord(), own, throttle=True, limits=None)
    assert step.write == TargetState(True, Limits(5000, 6000))


def test_a_throttle_already_on_is_a_human_decision():
    step = _step(TargetRecord(), HELD, throttle=True)
    assert step.action is Action.YIELD_ALREADY_THROTTLED
    assert step.write is None
    assert step.record.ownership is Ownership.YIELDED


def test_engaged_target_is_released_to_the_state_found_before():
    record = TargetRecord(Ownership.ENGAGED, before=OFF, applied=HELD)
    step = _step(record, HELD, throttle=False)
    assert step.action is Action.RELEASE
    assert step.write == OFF
    assert step.record.ownership is Ownership.IDLE
    assert (step.record.pending, step.record.pending_from) == (OFF, HELD)


def test_engaged_target_stays_held_while_demand_lasts():
    record = TargetRecord(Ownership.ENGAGED, before=OFF, applied=HELD)
    step = _step(record, HELD, throttle=True)
    assert step.action is Action.NONE
    assert step.record == record


def test_a_change_made_outside_waitarr_is_never_undone():
    record = TargetRecord(Ownership.ENGAGED, before=OFF, applied=HELD)
    turned_off = TargetState(False, SLOW)
    for throttle in (True, False):
        step = _step(record, turned_off, throttle=throttle)
        assert step.action is Action.YIELD_CHANGED_OUTSIDE
        assert step.write is None
        assert step.record.ownership is Ownership.YIELDED


def test_yielded_target_is_left_alone_until_demand_ends():
    yielded = TargetRecord(Ownership.YIELDED)
    held = _step(yielded, HELD, throttle=True)
    assert held.action is Action.NONE and held.write is None
    resumed = _step(yielded, HELD, throttle=False)
    assert resumed.action is Action.RESUME
    assert resumed.write is None
    assert resumed.record == TargetRecord()


def test_a_pending_write_is_retried_until_observed():
    record = TargetRecord(
        Ownership.ENGAGED, before=OFF, applied=HELD, pending=HELD
    )
    retry = _step(record, OFF, throttle=True)
    assert retry.action is Action.RETRY
    assert retry.write == HELD
    landed = _step(record, HELD, throttle=True)
    assert landed.action is Action.NONE
    assert landed.record.pending is None


def test_a_pending_release_is_confirmed_once_observed():
    record = TargetRecord(Ownership.IDLE, pending=OFF)
    assert _step(record, HELD, throttle=False).write == OFF
    confirmed = _step(record, OFF, throttle=False)
    assert confirmed.action is Action.CONFIRM
    assert confirmed.record == TargetRecord()


def test_simulation_expects_to_keep_observing_the_state_it_found():
    step = _step(TargetRecord(), OFF, throttle=True, simulate=True)
    assert step.action is Action.ENGAGE
    assert step.record.applied == OFF
    assert step.record.pending is None
    still = _step(step.record, OFF, throttle=True, simulate=True)
    assert still.action is Action.NONE
    human = _step(step.record, HELD, throttle=True, simulate=True)
    assert human.action is Action.YIELD_CHANGED_OUTSIDE


def test_restore_undoes_an_engage_that_may_not_have_landed():
    record = TargetRecord(
        Ownership.ENGAGED, before=OFF, applied=HELD, pending=HELD
    )
    partial = TargetState(False, SLOW)
    step = restore(record, partial)
    assert step.action is Action.RELEASE
    assert step.write == OFF


def test_restore_leaves_a_human_change_alone():
    record = TargetRecord(Ownership.ENGAGED, before=OFF, applied=HELD)
    step = restore(record, TargetState(False, SLOW))
    assert step.write is None


def test_limits_left_behind_by_a_human_switch_off_are_put_back():
    record = TargetRecord(Ownership.ENGAGED, before=OFF, applied=HELD)
    switched_off = TargetState(False, SLOW)
    yielded = _step(record, switched_off, throttle=True).record
    assert yielded.ownership is Ownership.YIELDED
    assert _step(yielded, switched_off, throttle=True).write is None
    resumed = _step(yielded, switched_off, throttle=False)
    assert resumed.action is Action.RESUME
    assert resumed.write == TargetState(False, OFF.limits)


def test_a_switch_a_human_turned_back_on_is_left_with_its_limits():
    record = TargetRecord(Ownership.YIELDED, before=OFF, applied=HELD)
    resumed = _step(record, HELD, throttle=False)
    assert resumed.action is Action.RESUME
    assert resumed.write is None


def test_a_pending_write_is_never_replayed_over_a_human_change():
    record = TargetRecord(
        Ownership.ENGAGED,
        before=OFF,
        applied=HELD,
        pending=HELD,
        pending_from=OFF,
    )
    human = TargetState(False, Limits(9 * 1024, 9 * 1024))
    step = _step(record, human, throttle=True)
    assert step.action is Action.YIELD_CHANGED_OUTSIDE
    assert step.write is None


def test_a_half_landed_write_is_retried():
    record = TargetRecord(
        Ownership.ENGAGED,
        before=OFF,
        applied=HELD,
        pending=HELD,
        pending_from=OFF,
    )
    halfway = TargetState(False, SLOW)
    step = _step(record, halfway, throttle=True)
    assert step.action is Action.RETRY
    assert step.write == HELD


def test_an_unconfirmed_engage_nobody_needs_is_undone_not_finished():
    record = TargetRecord(
        Ownership.ENGAGED,
        before=OFF,
        applied=HELD,
        pending=HELD,
        pending_from=OFF,
    )
    never_landed = _step(record, OFF, throttle=False)
    assert never_landed.write is None
    assert never_landed.record == TargetRecord()
    halfway = _step(record, TargetState(False, SLOW), throttle=False)
    assert halfway.action is Action.RELEASE
    assert halfway.write == OFF
