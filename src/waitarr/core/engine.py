"""The engine: one tick reads every source and target, asks the policy,
reconciles each target and, unless simulating, writes.

Safety rules enforced here rather than in an adapter:

- an unreadable source means the demand is unknown: no target changes;
- an unreadable target is left alone this tick;
- an unreadable task host means no task changes this tick, and never
  touches the health of the tick: the throttling goes on;
- with `simulate`, `ThrottleTarget.apply`, `TaskHost.stop` and
  `TaskHost.start` are never called and nothing is persisted --
  observation mode cannot change anything anywhere.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from waitarr.core.model import (
    Diagnostic,
    Limits,
    Playback,
    ScheduledTask,
    ServiceVersion,
    TargetState,
    TaskState,
)
from waitarr.core.policy import Demand, ThrottlePolicy
from waitarr.core.ports import (
    ActivitySource,
    Heartbeat,
    Notification,
    Notifier,
    ServiceUnavailable,
    Severity,
    StateStore,
    TaskHost,
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
from waitarr.core.tasks import (
    TaskAction,
    TaskOwnership,
    TaskRecord,
    TaskStep,
    TaskWrite,
    restore_task,
    step_task,
)
from waitarr.core.units import format_duration, format_rate

__all__ = [
    "Engine",
    "EngineStatus",
    "ServiceHealth",
    "TargetBinding",
    "TargetStatus",
    "TaskBinding",
    "TaskStatus",
]

logger = logging.getLogger("waitarr")

# While a service stays unreachable, its outage is logged once when it starts
# and then at most once per this interval.
UNREACHABLE_REMINDER = timedelta(minutes=10)

# `restore_all` waits this many seconds, at most, for a task being cancelled.
CANCEL_WAIT_SECONDS = 10

# The policy sees a task host as one more thing to hold; its name is
# prefixed so that it cannot collide with a target's.
_TASK_HOLD = "tasks:"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TargetBinding:
    """A target and the limits to apply while it is throttled (`None`
    keeps the target's own)."""

    target: ThrottleTarget
    throttle_limits: Limits | None = None


@dataclass(frozen=True)
class TaskBinding:
    """A task host, the task keys to hold while the policy asks for it, and
    whether Waitarr may stop them (off: it only reports them). Tasks it
    already stopped are started again either way."""

    host: TaskHost
    keys: tuple[str, ...] = ()
    suspend: bool = True


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
class TaskStatus:
    """A task Waitarr owns (stopped it, or yielded it to a human)."""

    ownership: TaskOwnership
    state: TaskState | None = None
    progress: float | None = None
    last_action: TaskAction | None = None
    last_action_at: datetime | None = None


@dataclass(frozen=True)
class EngineStatus:
    simulate: bool
    started_at: datetime
    last_tick_at: datetime | None
    playbacks: tuple[Playback, ...]
    services: dict[str, ServiceHealth]
    targets: dict[str, TargetStatus]
    diagnostics: tuple[Diagnostic, ...] = ()
    # Per task host, the tasks Waitarr owns; and the hosts that cannot be
    # read, with the reason. Neither changes `healthy`.
    tasks: dict[str, dict[str, TaskStatus]] = field(default_factory=dict)
    task_errors: dict[str, str] = field(default_factory=dict)

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
    down_since: datetime | None = None
    last_logged_at: datetime | None = None


@dataclass
class _TaskFeed:
    """What the engine remembers of one task host between ticks, in
    memory only: its outage, and the tasks it saw running during a hold
    (with the time it first saw them)."""

    down_since: datetime | None = None
    last_logged_at: datetime | None = None
    seen_running: dict[str, datetime] = field(default_factory=dict)


@dataclass
class _Runtime:
    last_tick_at: datetime | None = None
    playbacks: tuple[Playback, ...] = ()
    services: dict[str, ServiceHealth] = field(default_factory=dict)
    targets: dict[str, TargetStatus] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    tasks: dict[str, dict[str, TaskStatus]] = field(default_factory=dict)
    task_errors: dict[str, str] = field(default_factory=dict)


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
        task_hosts: Sequence[TaskBinding] = (),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not sources:
            raise ValueError("at least one activity source is required")
        if not targets:
            raise ValueError("at least one throttle target is required")
        self._sources = tuple(sources)
        self._targets = tuple(targets)
        self._task_hosts = tuple(task_hosts)
        self._sleep = sleep
        self._policy = policy
        self._store = store
        self._notifier = notifier
        self._heartbeat = heartbeat
        self._simulate = simulate
        self._failure_threshold = max(1, failure_threshold)
        self._clock = clock
        self._started_at = clock()
        self._document = StateDocument()
        self._activity_unknown = False
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
            tasks={b.host.name: {} for b in self._task_hosts},
        )
        self._feeds = {b.host.name: _TaskFeed() for b in self._task_hosts}
        self._sessions: dict[tuple[str, str], Playback] = {}

    @property
    def simulate(self) -> bool:
        return self._simulate

    @property
    def sources(self) -> tuple[ActivitySource, ...]:
        return self._sources

    @property
    def bindings(self) -> tuple[TargetBinding, ...]:
        return self._targets

    @property
    def task_bindings(self) -> tuple[TaskBinding, ...]:
        return self._task_hosts

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
        owned_tasks = sorted(
            (source, key)
            for source, records in document.tasks.items()
            for key, record in records.items()
            if record.ownership is not TaskOwnership.IDLE or record.pending
        )
        configured = {b.target.name for b in self._targets}
        configured_sources = {b.host.name for b in self._task_hosts}
        orphans = [name for name in owned if name not in configured]
        orphans += [
            f"the task {key} of {source}"
            for source, key in owned_tasks
            if source not in configured_sources
        ]
        if orphans and not self._simulate:
            raise StateDocumentError(
                f"the state file says Waitarr still owns {', '.join(orphans)}, "
                "which the configuration no longer declares. Restore it "
                "first with the previous configuration (`waitarr restore "
                "--yes`), or put it back under its old name."
            )
        if self._simulate:
            if owned or owned_tasks:
                logger.warning(
                    "The state file says a previous active run still owns "
                    "%s. Observation mode never writes, so it will not "
                    "give it back: run `waitarr restore` in active mode.",
                    ", ".join(
                        [*owned, *(f"{k} of {s}" for s, k in owned_tasks)]
                    ),
                )
            return
        document = replace(
            document,
            tasks={
                source: records
                for source, records in document.tasks.items()
                if source in configured_sources
            },
            task_memory={
                source: seen
                for source, seen in document.task_memory.items()
                if source in configured_sources
            },
        )
        self._document = document
        for name in owned:
            logger.info(
                "Resuming ownership of %s from the previous run (%s).",
                name,
                document.records[name].ownership.value,
            )
        for source, key in owned_tasks:
            logger.info(
                "Resuming ownership of the task %s of %s from the previous "
                "run (%s).",
                key,
                source,
                document.tasks[source][key].ownership.value,
            )
        with self._lock:
            for name, record in document.records.items():
                if name in self._runtime.targets:
                    self._runtime.targets[name] = TargetStatus(
                        record.ownership, None
                    )
            for source, key in owned_tasks:
                if source in self._runtime.tasks:
                    self._runtime.tasks[source][key] = TaskStatus(
                        document.tasks[source][key].ownership
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

    def diagnose(self) -> list[Diagnostic]:
        """Settings that defeat or weaken throttling; reads, never writes.

        The result is kept for the status endpoint until the next call.
        """
        found: list[Diagnostic] = []
        for binding in self._targets:
            target = binding.target
            try:
                found.extend(target.diagnose())
                own = target.read().limits
            except ServiceUnavailable as error:
                found.append(
                    Diagnostic(
                        target.name,
                        "warning",
                        f"{target.name}: cannot be checked ({error})",
                    )
                )
                continue
            if binding.throttle_limits is None and 0 in (
                own.download,
                own.upload,
            ):
                found.append(
                    Diagnostic(
                        target.name,
                        "warning",
                        f"{target.name}: no throttle limits are configured, "
                        "and its own alternative limits are "
                        f"{_describe_limits(own)}: throttling would leave "
                        "that direction unlimited. Set [throttle] download "
                        "and upload.",
                    )
                )
        with self._lock:
            self._runtime.diagnostics = tuple(found)
        return found

    def tick(self) -> None:
        now = self._clock()
        playbacks = self._read_playbacks(now)
        if playbacks is None:
            if not self._activity_unknown:
                self._activity_unknown = True
                logger.warning(
                    "Activity unknown: no target is changed until every "
                    "source answers."
                )
        else:
            self._activity_unknown = False
            self._log_playback_changes(playbacks)
            names = [b.target.name for b in self._targets]
            names += [_TASK_HOLD + b.host.name for b in self._task_hosts]
            result = self._policy.decide(
                playbacks,
                names,
                now,
                {
                    **self._document.memory,
                    **{
                        _TASK_HOLD + source: seen
                        for source, seen in self._document.task_memory.items()
                    },
                },
            )
            self._document = replace(
                self._document,
                memory={
                    name: seen
                    for name, seen in result.memory.items()
                    if not name.startswith(_TASK_HOLD)
                },
                task_memory={
                    name[len(_TASK_HOLD) :]: seen
                    for name, seen in result.memory.items()
                    if name.startswith(_TASK_HOLD)
                },
            )
            for binding in self._targets:
                demand = result.demands[binding.target.name]
                self._tick_target(binding, demand, now)
            for task_binding in self._task_hosts:
                demand = result.demands[_TASK_HOLD + task_binding.host.name]
                self._tick_tasks(task_binding, demand, now)
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
            for task_binding in self._task_hosts:
                source = task_binding.host.name
                for key, task in self._document.tasks.get(source, {}).items():
                    if task.ownership is TaskOwnership.STOPPED:
                        logger.info(
                            "%s: [observe] would start task %s again.",
                            source,
                            key,
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
        for task_binding in self._task_hosts:
            if not self._restore_tasks(task_binding, now):
                complete = False
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
                diagnostics=self._runtime.diagnostics,
                tasks={s: dict(t) for s, t in self._runtime.tasks.items()},
                task_errors=dict(self._runtime.task_errors),
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
            logger.debug(
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

    # -- tasks -------------------------------------------------------------

    def _task_records(self, source: str) -> dict[str, TaskRecord]:
        return dict(self._document.tasks.get(source, {}))

    def _set_task_record(
        self, source: str, key: str, record: TaskRecord
    ) -> None:
        records = self._task_records(source)
        if record.ownership is TaskOwnership.IDLE:
            records.pop(key, None)
        else:
            records[key] = record
        tasks = dict(self._document.tasks)
        tasks[source] = records
        self._document = replace(self._document, tasks=tasks)

    def _read_tasks(
        self, binding: TaskBinding, now: datetime
    ) -> dict[str, ScheduledTask] | None:
        """The host's tasks by key, or `None` when it cannot be read. An
        outage is logged and shown in the status, nothing more."""
        source = binding.host.name
        feed = self._feeds[source]
        try:
            listed = binding.host.tasks()
        except ServiceUnavailable as error:
            self._task_failed(source, feed, str(error), now)
            return None
        if feed.down_since is not None:
            logger.info(
                "%s: its tasks can be read again after %s.",
                source,
                format_duration(now - feed.down_since),
            )
            feed.down_since = None
            feed.last_logged_at = None
            with self._lock:
                self._runtime.task_errors.pop(source, None)
        return {task.key: task for task in listed}

    def _task_failed(
        self, source: str, feed: _TaskFeed, error: str, now: datetime
    ) -> None:
        if feed.down_since is None:
            feed.down_since = now
            feed.last_logged_at = now
            logger.warning(
                "%s: its tasks cannot be read, none is changed until they "
                "can: %s",
                source,
                error,
            )
        elif (
            feed.last_logged_at is None
            or now - feed.last_logged_at >= UNREACHABLE_REMINDER
        ):
            feed.last_logged_at = now
            logger.warning(
                "%s: its tasks still cannot be read after %s (%s).",
                source,
                format_duration(now - feed.down_since),
                error,
            )
        with self._lock:
            self._runtime.task_errors[source] = error

    def _tick_tasks(
        self, binding: TaskBinding, demand: Demand, now: datetime
    ) -> None:
        source = binding.host.name
        feed = self._feeds[source]
        records = self._task_records(source)
        # No call when nothing holds, nothing is owned and nothing was seen
        # running: an idle Waitarr costs the host nothing.
        if not (demand.throttle or records or feed.seen_running):
            return
        observed = self._read_tasks(binding, now)
        if observed is None:
            return
        self._log_task_activity(binding, feed, observed, demand.throttle, now)
        keys = [*binding.keys, *(k for k in records if k not in binding.keys)]
        for key in keys:
            self._tick_task(binding, key, observed.get(key), demand, now)

    def _tick_task(
        self,
        binding: TaskBinding,
        key: str,
        observed: ScheduledTask | None,
        demand: Demand,
        now: datetime,
    ) -> None:
        source = binding.host.name
        record = self._task_records(source).get(key, TaskRecord())
        suspend = binding.suspend and key in binding.keys
        step = step_task(
            record,
            observed,
            hold=demand.throttle,
            suspend=suspend,
            simulate=self._simulate,
        )
        self._log_task_step(source, key, observed, step, demand)
        if self._simulate or step.write is None:
            self._set_task_record(source, key, step.record)
            self._publish_task(source, key, step, observed, now)
            return
        assert observed is not None
        self._execute_task(
            binding,
            key,
            observed,
            step,
            now,
            hold=demand.throttle,
            suspend=suspend,
        )

    def _execute_task(
        self,
        binding: TaskBinding,
        key: str,
        observed: ScheduledTask,
        step: TaskStep,
        now: datetime,
        *,
        hold: bool,
        suspend: bool,
    ) -> bool:
        """Write ahead, send, read back. Returns whether the write landed.

        The task is then judged by the same machine as at the next tick,
        so that a stop still being cancelled stays pending until its first
        idle reading.
        """
        host = binding.host
        source = host.name
        self._set_task_record(source, key, step.record)
        self._save()
        try:
            if step.write is TaskWrite.STOP:
                host.stop(observed.id)
            else:
                host.start(observed.id)
            after = self._read_tasks(binding, now)
        except ServiceUnavailable as error:
            logger.error(
                "%s: task %s: %s failed (%s); it will be retried next tick.",
                source,
                key,
                step.write.value if step.write else "write",
                error,
            )
            self._publish_task(source, key, step, observed, now)
            return False
        if after is None:
            self._publish_task(source, key, step, observed, now)
            return False
        after_task = after.get(key)
        settled = step_task(
            step.record,
            after_task,
            hold=hold,
            suspend=suspend,
            simulate=False,
        )
        landed = settled.write is None
        if landed:
            self._set_task_record(source, key, settled.record)
            self._save()
        else:
            logger.warning(
                "%s: task %s: the %s did not land; retrying next tick.",
                source,
                key,
                step.write.value if step.write else "write",
            )
        self._publish_task(source, key, step, after_task, now)
        return landed

    def _restore_tasks(self, binding: TaskBinding, now: datetime) -> bool:
        """Start again every task Waitarr stopped. A task being cancelled
        is waited for, a few seconds at most; if it is still not idle, its
        record stays for the next start."""
        source = binding.host.name
        records = {
            key: record
            for key, record in self._task_records(source).items()
            if record.ownership is not TaskOwnership.IDLE or record.pending
        }
        if not records:
            return True
        observed = self._read_tasks(binding, now)
        if observed is None:
            logger.error(
                "%s: its tasks cannot be read, they cannot be restored now; "
                "the state file keeps what to restore at the next start.",
                source,
            )
            return False
        complete = True
        for key, record in records.items():
            step = restore_task(record, observed.get(key))
            for _ in range(CANCEL_WAIT_SECONDS):
                if step.action is not TaskAction.WAIT:
                    break
                self._sleep(1.0)
                observed = self._read_tasks(binding, now)
                if observed is None:
                    return False
                step = restore_task(record, observed.get(key))
            if step.action is TaskAction.WAIT:
                complete = False
                logger.error(
                    "%s: task %s is still being cancelled; the state file "
                    "keeps it, it is started again at the next start.",
                    source,
                    key,
                )
                continue
            task = observed.get(key)
            self._log_task_step(source, key, task, step, None)
            if step.write is None:
                self._set_task_record(source, key, step.record)
                self._publish_task(source, key, step, task, now)
                continue
            assert task is not None
            landed = self._execute_task(
                binding, key, task, step, now, hold=False, suspend=False
            )
            complete = complete and landed
        return complete

    def _publish_task(
        self,
        source: str,
        key: str,
        step: TaskStep,
        observed: ScheduledTask | None,
        now: datetime,
        *,
        action: TaskAction | None = None,
    ) -> None:
        action = action or step.action
        record = self._task_records(source).get(key)
        with self._lock:
            tasks = self._runtime.tasks[source]
            previous = tasks.get(key)
            if record is None:
                tasks.pop(key, None)
                return
            if action in (TaskAction.NONE, TaskAction.WAIT) and previous:
                last_action, last_action_at = (
                    previous.last_action,
                    previous.last_action_at,
                )
            else:
                last_action, last_action_at = action, now
            tasks[key] = TaskStatus(
                ownership=record.ownership,
                state=observed.state if observed else None,
                progress=observed.progress if observed else None,
                last_action=last_action,
                last_action_at=last_action_at,
            )

    def _log_task_activity(
        self,
        binding: TaskBinding,
        feed: _TaskFeed,
        observed: dict[str, ScheduledTask],
        hold: bool,
        now: datetime,
    ) -> None:
        """One line when a listed task is seen running during a hold, one
        when it ends -- whatever the option and whoever owns the task."""
        source = binding.host.name
        for key in binding.keys:
            task = observed.get(key)
            active = task is not None and task.state is not TaskState.IDLE
            if active and hold and key not in feed.seen_running:
                assert task is not None
                feed.seen_running[key] = now
                logger.info(
                    "%s: task %s is running (%s), seen since %s.",
                    source,
                    _task_label(task, key),
                    _describe_progress(task),
                    now.astimezone().strftime("%H:%M"),
                )
            elif not active and key in feed.seen_running:
                del feed.seen_running[key]
                logger.info(
                    "%s: task %s is no longer running.",
                    source,
                    _task_label(task, key),
                )

    def _log_task_step(
        self,
        source: str,
        key: str,
        observed: ScheduledTask | None,
        step: TaskStep,
        demand: Demand | None,
    ) -> None:
        would = "[observe] would " if self._simulate else ""
        label = _task_label(observed, key)
        action = step.action
        if action is TaskAction.STOP and observed is not None:
            why = ""
            if demand is not None and demand.playbacks:
                why = " -- " + "; ".join(p.describe() for p in demand.playbacks)
            logger.info(
                "%s: %sstop task %s (%s)%s.",
                source,
                would,
                label,
                _describe_progress(observed),
                why,
            )
        elif action is TaskAction.START:
            logger.info(
                "%s: %sstart task %s again (it restarts from zero).",
                source,
                would,
                label,
            )
        elif action is TaskAction.CONFIRM:
            logger.info(
                "%s: task %s was stopped by Waitarr; it is started again "
                "when playback has stopped.",
                source,
                label,
            )
        elif action is TaskAction.YIELD:
            logger.info(
                "%s: task %s is running again: a human decision, left "
                "alone until playback stops.",
                source,
                label,
            )
        elif action is TaskAction.FORGET and observed is None:
            logger.warning(
                "%s: task %s is no longer listed; Waitarr forgets it.",
                source,
                key,
            )
        elif action is TaskAction.FORGET:
            logger.info(
                "%s: task %s needs nothing more from Waitarr; forgotten.",
                source,
                label,
            )
        elif action is TaskAction.RETRY and step.write is not None:
            logger.warning(
                "%s: a previous %s of task %s did not land; retrying.",
                source,
                step.write.value,
                label,
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
        if tracker.down_since is not None:
            logger.info(
                "%s: reachable again after %s.",
                name,
                format_duration(now - tracker.down_since),
            )
        tracker.down_since = None
        tracker.last_logged_at = None
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
        if tracker.down_since is None:
            tracker.down_since = now
            tracker.last_logged_at = now
            logger.warning("%s: %s", name, error)
        elif (
            tracker.last_logged_at is None
            or now - tracker.last_logged_at >= UNREACHABLE_REMINDER
        ):
            tracker.last_logged_at = now
            logger.warning(
                "%s: still unreachable after %s (%s).",
                name,
                format_duration(now - tracker.down_since),
                error,
            )
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
        """One line per session change, so every decision logged next is
        explained by the line just before it."""
        current = {(p.source, p.session_id): p for p in playbacks}
        for key, playback in current.items():
            previous = self._sessions.get(key)
            if previous is None:
                verb = "started, paused," if playback.paused else "started"
            elif previous.title != playback.title:
                verb = "now plays"
            elif previous.paused and not playback.paused:
                verb = "resumed"
            elif playback.paused and not previous.paused:
                verb = "paused"
            else:
                continue
            logger.info("Session: %s.", _session_line(playback, verb))
        for key, playback in self._sessions.items():
            if key not in current:
                logger.info("Session: %s.", _session_line(playback, "stopped"))
        if self._sessions and not current:
            logger.info("No session is playing anything.")
        self._sessions = current

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
            if demand is None:
                reason = "Waitarr is giving back what it owns"
            elif demand.last_activity_at is not None:
                quiet = format_duration(self._clock() - demand.last_activity_at)
                reason = f"no counted playback for {quiet}"
            else:
                reason = "no counted playback"
            logger.info(
                "%s: %srelease, restoring the state found before (%s) -- %s.",
                name,
                would,
                _describe_state(step.write),
                reason,
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
        held = sum(
            1
            for tasks in status.tasks.values()
            for task in tasks.values()
            if task.ownership is TaskOwnership.STOPPED
        )
        if held:
            parts.append(f"{held} task(s) held")
        down = [n for n, s in status.services.items() if s.reachable is False]
        if down:
            parts.append("unreachable: " + ", ".join(down))
        return ", ".join(parts)


def _task_label(task: ScheduledTask | None, key: str) -> str:
    return f"{task.name} ({key})" if task is not None else key


def _describe_progress(task: ScheduledTask) -> str:
    if task.progress is None:
        return "progress unknown"
    return f"{task.progress:.0f}% done"


def _session_line(playback: Playback, verb: str) -> str:
    who = playback.user or "someone"
    what = f'"{playback.title}"' if playback.title else "something"
    where = " on ".join(p for p in (playback.device, playback.client) if p)
    return f"{who} {verb} {what}" + (f" ({where})" if where else "")


def _describe_limits(limits: Limits) -> str:
    return (
        f"{format_rate(limits.download)} down, {format_rate(limits.upload)} up"
    )


def _describe_state(state: TargetState) -> str:
    mode = "on" if state.throttled else "off"
    return f"alternative mode {mode}, limits {_describe_limits(state.limits)}"
