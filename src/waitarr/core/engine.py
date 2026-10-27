"""The engine: one tick reads every source and target, asks the policy,
reconciles each target and, unless simulating, writes.

Safety rules enforced here rather than in an adapter:

- an unreadable source means the demand is unknown: no target changes;
- an unreadable target is left alone this tick;
- with `simulate`, `ThrottleTarget.apply` is never called and nothing
  is persisted -- observation mode cannot change anything anywhere.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from waitarr.core.model import Limits, Playback, ServiceVersion, TargetState
from waitarr.core.policy import Demand, ThrottlePolicy
from waitarr.core.ports import (
    ActivitySource,
    Heartbeat,
    Notification,
    Notifier,
    ServiceUnavailable,
    Severity,
    StateStore,
    ThrottleTarget,
)
from waitarr.core.reconcile import (
    Action,
    Ownership,
    Step,
    TargetRecord,
    reconcile,
    restore,
)
from waitarr.core.records import (
    StateDocument,
    StateDocumentError,
    decode_state,
    encode_state,
)
from waitarr.core.units import format_rate

__all__ = [
    "Engine",
    "EngineStatus",
    "ServiceHealth",
    "TargetBinding",
    "TargetStatus",
]

logger = logging.getLogger("waitarr")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TargetBinding:
    """A target and the limits to apply while it is throttled (`None`
    keeps the target's own)."""

    target: ThrottleTarget
    throttle_limits: Limits | None = None


@dataclass(frozen=True)
class ServiceHealth:
    kind: str
    reachable: bool | None = None
    error: str | None = None
    since: datetime | None = None
    version: ServiceVersion | None = None


@dataclass(frozen=True)
class TargetStatus:
    ownership: Ownership
    observed: TargetState | None
    last_action: Action | None = None
    last_action_at: datetime | None = None


@dataclass(frozen=True)
class EngineStatus:
    simulate: bool
    started_at: datetime
    last_tick_at: datetime | None
    playbacks: tuple[Playback, ...]
    services: dict[str, ServiceHealth]
    targets: dict[str, TargetStatus]

    @property
    def healthy(self) -> bool:
        return self.last_tick_at is not None and all(
            s.reachable for s in self.services.values()
        )


@dataclass
class _Tracker:
    """Consecutive failures of one service, for debounced notifications."""

    failures: int = 0
    notified: bool = False


@dataclass
class _Runtime:
    last_tick_at: datetime | None = None
    playbacks: tuple[Playback, ...] = ()
    services: dict[str, ServiceHealth] = field(default_factory=dict)
    targets: dict[str, TargetStatus] = field(default_factory=dict)


class Engine:
    def __init__(
        self,
        *,
        sources: Sequence[ActivitySource],
        targets: Sequence[TargetBinding],
        policy: ThrottlePolicy,
        store: StateStore,
        notifier: Notifier,
        heartbeat: Heartbeat,
        simulate: bool,
        failure_threshold: int = 2,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not sources:
            raise ValueError("at least one activity source is required")
        if not targets:
            raise ValueError("at least one throttle target is required")
        self._sources = tuple(sources)
        self._targets = tuple(targets)
        self._policy = policy
        self._store = store
        self._notifier = notifier
        self._heartbeat = heartbeat
        self._simulate = simulate
        self._failure_threshold = max(1, failure_threshold)
        self._clock = clock
        self._started_at = clock()
        self._document = StateDocument()
        self._trackers: dict[str, _Tracker] = {}
        self._lock = threading.Lock()
        self._runtime = _Runtime(
            services={
                **{s.name: ServiceHealth("source") for s in self._sources},
                **{b.target.name: ServiceHealth("target") for b in targets},
            },
            targets={
                b.target.name: TargetStatus(Ownership.IDLE, None)
                for b in targets
            },
        )
        self._previous_sessions: frozenset[tuple[str, str]] = frozenset()

    @property
    def simulate(self) -> bool:
        return self._simulate

    @property
    def sources(self) -> tuple[ActivitySource, ...]:
        return self._sources

    @property
    def bindings(self) -> tuple[TargetBinding, ...]:
        return self._targets

    # -- lifecycle ---------------------------------------------------------

    def load(self) -> None:
        """Load what a previous run owned.

        Raises `StateDocumentError` on a corrupt file: guessing what to
        restore is worse than refusing to start.
        """
        document = decode_state(self._store.load())
        owned = sorted(
            name
            for name, record in document.records.items()
            if record.ownership is not Ownership.IDLE or record.pending
        )
        configured = {b.target.name for b in self._targets}
        orphans = [name for name in owned if name not in configured]
        if orphans and not self._simulate:
            raise StateDocumentError(
                f"the state file says Waitarr still owns {', '.join(orphans)}, "
                "which the configuration no longer declares. Restore it "
                "first with the previous configuration (`waitarr restore "
                "--yes`), or put the target back under its old name."
            )
        if self._simulate:
            if owned:
                logger.warning(
                    "The state file says a previous active run still owns "
                    "%s. Observation mode never writes, so it will not "
                    "give it back: run `waitarr restore` in active mode.",
                    ", ".join(owned),
                )
            return
        self._document = document
        for name in owned:
            logger.info(
                "Resuming ownership of %s from the previous run (%s).",
                name,
                document.records[name].ownership.value,
            )
        with self._lock:
            for name, record in document.records.items():
                if name in self._runtime.targets:
                    self._runtime.targets[name] = TargetStatus(
                        record.ownership, None
                    )

    def check_versions(self) -> dict[str, ServiceVersion | None]:
        """Read each service's version once, for the compatibility check."""
        versions: dict[str, ServiceVersion | None] = {}
        services: list[ActivitySource | ThrottleTarget] = [
            *self._sources,
            *(b.target for b in self._targets),
        ]
        for service in services:
            try:
                versions[service.name] = service.version()
            except ServiceUnavailable as error:
                logger.warning(
                    "%s: cannot read its version: %s", service.name, error
                )
                versions[service.name] = None
                continue
            with self._lock:
                health = self._runtime.services[service.name]
                self._runtime.services[service.name] = replace(
                    health, version=versions[service.name]
                )
        return versions

    def diagnose(self) -> list[str]:
        """Warnings worth reading at startup; reads, never writes."""
        warnings: list[str] = []
        for binding in self._targets:
            target = binding.target
            try:
                warnings.extend(target.diagnose())
                own = target.read().limits
            except ServiceUnavailable as error:
                warnings.append(f"{target.name}: cannot be checked ({error})")
                continue
            if binding.throttle_limits is None and 0 in (
                own.download,
                own.upload,
            ):
                warnings.append(
                    f"{target.name}: no throttle limits are configured, and "
                    f"its own alternative limits are {_describe_limits(own)}: "
                    "throttling would leave that direction unlimited. Set "
                    "[throttle] download and upload."
                )
        return warnings

    def tick(self) -> None:
        now = self._clock()
        playbacks = self._read_playbacks(now)
        if playbacks is None:
            logger.warning(
                "Activity unknown this tick: no target is changed until "
                "every source answers."
            )
        else:
            self._log_playback_changes(playbacks)
            names = [b.target.name for b in self._targets]
            result = self._policy.decide(
                playbacks, names, now, self._document.memory
            )
            self._document = replace(self._document, memory=result.memory)
            for binding in self._targets:
                demand = result.demands[binding.target.name]
                self._tick_target(binding, demand, now)
            self._save()
        with self._lock:
            self._runtime.last_tick_at = now
            if playbacks is not None:
                self._runtime.playbacks = tuple(playbacks)
        status = self.status()
        self._heartbeat.beat(
            healthy=status.healthy, message=self._summary(status)
        )

    def restore_all(self) -> bool:
        """Give back every target Waitarr owns. Returns whether all were
        restored (or owned nothing); a target that cannot be read keeps
        its record, so the next start restores it."""
        if self._simulate:
            for binding in self._targets:
                record = self._record(binding.target.name)
                if record.ownership is Ownership.ENGAGED:
                    logger.info(
                        "[observe] %s: would restore the state found before.",
                        binding.target.name,
                    )
            return True
        complete = True
        now = self._clock()
        for binding in self._targets:
            target = binding.target
            record = self._record(target.name)
            if record.ownership is Ownership.IDLE and record.pending is None:
                continue
            observed = self._read_target(target, now)
            if observed is None:
                complete = False
                logger.error(
                    "%s: unreachable, cannot restore it now; the state file "
                    "keeps what to restore at the next start.",
                    target.name,
                )
                continue
            step = restore(record, observed)
            self._log_step(target.name, step, observed, None, binding)
            landed = self._execute(target, step, now)
            complete = complete and landed
            shown = step.write if landed and step.write else observed
            self._publish_target(target.name, step.action, shown, now)
        self._save()
        return complete

    # -- status ------------------------------------------------------------

    def status(self) -> EngineStatus:
        with self._lock:
            return EngineStatus(
                simulate=self._simulate,
                started_at=self._started_at,
                last_tick_at=self._runtime.last_tick_at,
                playbacks=self._runtime.playbacks,
                services=dict(self._runtime.services),
                targets=dict(self._runtime.targets),
            )

    # -- internals ---------------------------------------------------------

    def _record(self, name: str) -> TargetRecord:
        return self._document.records.get(name, TargetRecord())

    def _set_record(self, name: str, record: TargetRecord) -> None:
        records = dict(self._document.records)
        records[name] = record
        self._document = replace(self._document, records=records)

    def _save(self) -> None:
        if self._simulate:
            return
        self._store.save(encode_state(self._document))

    def _read_playbacks(self, now: datetime) -> list[Playback] | None:
        playbacks: list[Playback] = []
        complete = True
        for source in self._sources:
            try:
                playbacks.extend(source.playbacks())
            except ServiceUnavailable as error:
                complete = False
                self._service_failed(source.name, str(error), now)
                continue
            self._service_ok(source.name, now)
        return playbacks if complete else None

    def _read_target(
        self, target: ThrottleTarget, now: datetime
    ) -> TargetState | None:
        try:
            observed = target.read()
        except ServiceUnavailable as error:
            self._service_failed(target.name, str(error), now)
            return None
        self._service_ok(target.name, now)
        return observed

    def _tick_target(
        self, binding: TargetBinding, demand: Demand, now: datetime
    ) -> None:
        target = binding.target
        observed = self._read_target(target, now)
        if observed is None:
            logger.warning(
                "%s: state unknown this tick, leaving it untouched.",
                target.name,
            )
            return
        step = reconcile(
            self._record(target.name),
            observed,
            throttle=demand.throttle,
            throttle_limits=binding.throttle_limits,
            simulate=self._simulate,
        )
        self._log_step(target.name, step, observed, demand, binding)
        if self._simulate or step.write is None:
            self._set_record(target.name, step.record)
            self._publish_target(target.name, step.action, observed, now)
            return
        landed = self._execute(target, step, now)
        shown = step.write if landed else observed
        self._publish_target(target.name, step.action, shown, now)

    def _execute(
        self, target: ThrottleTarget, step: Step, now: datetime
    ) -> bool:
        """Write ahead, apply, confirm. Returns whether the write landed."""
        self._set_record(target.name, step.record)
        if step.write is None:
            return True
        self._save()
        try:
            target.apply(step.write)
            confirmed = target.read()
        except ServiceUnavailable as error:
            self._service_failed(target.name, f"write failed: {error}", now)
            logger.error(
                "%s: write failed (%s); it will be retried next tick.",
                target.name,
                error,
            )
            return False
        if confirmed != step.write:
            logger.warning(
                "%s: wrote %s but read back %s; retrying next tick.",
                target.name,
                _describe_state(step.write),
                _describe_state(confirmed),
            )
            return False
        self._set_record(target.name, replace(step.record, pending=None))
        self._save()
        return True

    def _publish_target(
        self, name: str, action: Action, observed: TargetState, now: datetime
    ) -> None:
        with self._lock:
            previous = self._runtime.targets.get(name)
            if action is Action.NONE and previous is not None:
                last_action = previous.last_action
                last_action_at = previous.last_action_at
            else:
                last_action, last_action_at = action, now
            self._runtime.targets[name] = TargetStatus(
                ownership=self._record(name).ownership,
                observed=observed,
                last_action=last_action,
                last_action_at=last_action_at,
            )

    def _service_ok(self, name: str, now: datetime) -> None:
        tracker = self._trackers.setdefault(name, _Tracker())
        if tracker.notified:
            self._notifier.notify(
                Notification(
                    Severity.RECOVERY,
                    f"Waitarr: {name} is reachable again",
                    f"{name} answered again; Waitarr resumes normal work.",
                )
            )
            logger.info("%s: reachable again.", name)
        tracker.failures = 0
        tracker.notified = False
        with self._lock:
            health = self._runtime.services[name]
            if health.reachable is not True:
                self._runtime.services[name] = replace(
                    health, reachable=True, error=None, since=now
                )

    def _service_failed(self, name: str, error: str, now: datetime) -> None:
        tracker = self._trackers.setdefault(name, _Tracker())
        tracker.failures += 1
        logger.warning("%s: %s", name, error)
        if tracker.failures >= self._failure_threshold and not tracker.notified:
            tracker.notified = True
            self._notifier.notify(
                Notification(
                    Severity.FAILURE,
                    f"Waitarr: {name} is unreachable",
                    f"{name}: {error}. Waitarr changes nothing that depends "
                    "on it until it answers again.",
                )
            )
        with self._lock:
            health = self._runtime.services[name]
            since = health.since if health.reachable is False else now
            self._runtime.services[name] = replace(
                health, reachable=False, error=error, since=since
            )

    def _log_playback_changes(self, playbacks: Sequence[Playback]) -> None:
        sessions = frozenset((p.source, p.session_id) for p in playbacks)
        if sessions == self._previous_sessions:
            return
        self._previous_sessions = sessions
        if playbacks:
            logger.info(
                "Sessions now: %s.",
                "; ".join(
                    p.describe() + (" [paused]" if p.paused else "")
                    for p in playbacks
                ),
            )
        else:
            logger.info("No session is playing anything.")

    def _log_step(
        self,
        name: str,
        step: Step,
        observed: TargetState,
        demand: Demand | None,
        binding: TargetBinding,
    ) -> None:
        would = "[observe] would " if self._simulate else ""
        why = ""
        if demand is not None and demand.playbacks:
            why = " -- " + "; ".join(p.describe() for p in demand.playbacks)
        action = step.action
        if action is Action.ENGAGE and step.write is not None:
            logger.info(
                "%s: %sthrottle (alternative limits on: %s)%s.",
                name,
                would,
                _describe_limits(step.write.limits),
                why,
            )
        elif action is Action.RELEASE and step.write is not None:
            logger.info(
                "%s: %srelease, restoring the state found before (%s).",
                name,
                would,
                _describe_state(step.write),
            )
        elif action is Action.YIELD_ALREADY_THROTTLED:
            logger.info(
                "%s: alternative limits were already on before Waitarr: a "
                "human decision, left alone until playback stops.",
                name,
            )
        elif action is Action.YIELD_CHANGED_OUTSIDE:
            logger.info(
                "%s: changed outside Waitarr (now %s): a human decision, "
                "left alone until playback stops.",
                name,
                _describe_state(observed),
            )
        elif action is Action.RESUME and step.write is not None:
            logger.info(
                "%s: playback has stopped; %sput back the alternative limits "
                "found before (%s), the switch stays as a human set it.",
                name,
                would,
                _describe_limits(step.write.limits),
            )
        elif action is Action.RESUME:
            logger.info(
                "%s: playback has stopped; Waitarr manages this target again.",
                name,
            )
        elif action is Action.RETRY and step.write is not None:
            logger.warning(
                "%s: a previous write did not land; retrying (%s).",
                name,
                _describe_state(step.write),
            )

    def _summary(self, status: EngineStatus) -> str:
        parts = [f"{'observe' if self._simulate else 'active'} mode"]
        parts.append(f"{len(status.playbacks)} session(s)")
        for name, target in status.targets.items():
            parts.append(f"{name}={target.ownership.value}")
        down = [n for n, s in status.services.items() if s.reachable is False]
        if down:
            parts.append("unreachable: " + ", ".join(down))
        return ", ".join(parts)


def _describe_limits(limits: Limits) -> str:
    return (
        f"{format_rate(limits.download)} down, {format_rate(limits.upload)} up"
    )


def _describe_state(state: TargetState) -> str:
    mode = "on" if state.throttled else "off"
    return f"alternative mode {mode}, limits {_describe_limits(state.limits)}"
