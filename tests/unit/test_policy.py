from datetime import timedelta

from tests.fakes import FakeClock, playback
from waitarr.core.policy import GlobalHysteresisPolicy, PlaybackFilter


def _policy(**filters):
    return GlobalHysteresisPolicy(
        release_after=timedelta(minutes=3),
        playback_filter=PlaybackFilter.build(**filters),
    )


def test_any_playback_throttles_every_target():
    clock = FakeClock()
    result = _policy().decide([playback()], ["a", "b"], clock(), {})
    assert all(d.throttle for d in result.demands.values())
    assert result.memory == {"a": clock(), "b": clock()}


def test_hold_lasts_release_after_then_lets_go():
    clock = FakeClock()
    policy = _policy()
    memory = policy.decide([playback()], ["a"], clock(), {}).memory
    clock.advance(179)
    held = policy.decide([], ["a"], clock(), memory)
    assert held.demands["a"].throttle
    clock.advance(1)
    released = policy.decide([], ["a"], clock(), held.memory)
    assert not released.demands["a"].throttle
    assert released.memory == {}


def test_paused_sessions_do_not_count_by_default():
    clock = FakeClock()
    paused = [playback(paused=True)]
    assert (
        not _policy().decide(paused, ["a"], clock(), {}).demands["a"].throttle
    )
    counted = _policy(count_paused=True).decide(paused, ["a"], clock(), {})
    assert counted.demands["a"].throttle


def test_filters_are_case_insensitive():
    f = PlaybackFilter.build(
        users=["Alice", "Bob"],
        ignore_devices=["kitchen speaker"],
        media_types=["movie", "Episode"],
    )
    assert f.matches(playback("alice"))
    assert not f.matches(playback("carol"))
    assert not f.matches(playback("bob", device="Kitchen Speaker"))
    assert not f.matches(playback("bob", media_type="Audio"))


def test_ignore_lists_never_exclude_an_unknown_value():
    f = PlaybackFilter.build(ignore_users=["guest"], ignore_clients=["DLNA"])
    assert f.matches(playback(user="", client=None))
    assert not PlaybackFilter.build(users=["alice"]).matches(playback(user=""))
