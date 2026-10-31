# 0013. Stop Jellyfin's heavy scheduled tasks during a playback

- Status: accepted (2026-10-31)

## Context

On 2026-10-30 the library scan (`RefreshLibrary`, every 12 hours) ran for
about four minutes during a film, and the transcoder fell below real
time for about ten minutes around it. The scan did not explain the whole
window, but it is the one disk load Waitarr could not see. It is now
scheduled at night; a late playback, or a manual launch, can still land on
it.

## Decision

- Each Jellyfin source gets `suspend_tasks` (default `true`, as for
  throttling in [ADR 0012](0012-active-by-default.md)) and `tasks`, the
  scheduled tasks to hold, by `Key` (default: `RefreshLibrary`,
  `TaskExtractMediaSegments`, `RefreshChapterImages`,
  `RefreshTrickplayImages`).
- The hold is the policy's throttle demand: same `release_after`, same
  filter, same memory, kept per source beside the tasks in the state file.
- During the hold, a listed task found `Running` is stopped. At the end,
  each task Waitarr stopped is started again if nothing ran it since (its
  last execution is still the cancelled one). A task restarts from zero.
- A task Waitarr stopped and found running again was started by a person:
  it is left alone until the end of the hold, then forgotten.
- Same discipline as [ADR 0003](0003-ownership-state-machine.md): the
  write is recorded as `pending` before it is sent and cleared after the
  read back; a crash is resolved from what Jellyfin reports.
- Observation mode cannot write, in three layers as in
  [ADR 0004](0004-observation-mode-cannot-write.md): the engine never
  calls `stop` or `start` when simulating, the adapter raises
  `WriteRefused` when built read-only, and its request method refuses
  everything but `GET`.
- An unreadable `/ScheduledTasks` changes no task and does not change the
  health: throttling goes on, the reason is under `task_errors`. A
  configured key Jellyfin does not list is a warning, never an error.

## Facts probed (Jellyfin 12.2.0, disposable container)

- A task is called by `Id` (made up per instance) and identified by `Key`.
  `State` is `Idle`, `Running` or `Cancelling`.
- Stopping a running task answers 204; it is `Cancelling` for 4 to 7
  seconds, then `Idle` with a `Cancelled` last execution. While
  `Cancelling`, the last execution is still the previous one.
- Stopping an idle task answers 500, also when it has just finished: the
  adapter reads again and treats "no longer running" as done.
- Starting a task answers 204; if it is running, it is ignored. The task
  starts from 0 % and the last execution keeps the old result until it
  ends. An unknown `Id` answers 404; a user token, 403.
- `POST /Library/Refresh` (the dashboard's scan button) runs the same
  `RefreshLibrary`. Nothing tells a scheduled start from a manual one.

## Consequences

- The state file moves to schema 2 (a `tasks` section per source). Version
  1 files are read; version 2 files are refused by an older Waitarr.
- An execution is identified by the `StartTimeUtc` Jellyfin reports,
  compared as text, never by Waitarr's clock; a missing last execution is
  an identity of its own. The `Id` is never stored.
- While `Cancelling`, Waitarr writes nothing (neither stop nor start was
  probed in that state) and waits for the first `Idle`.
- Stopping Waitarr during a playback starts the owned tasks again, as it
  gives the qBittorrent limits back; the restore waits at most 10 seconds
  for a task that is still `Cancelling`.
- A task removed from `tasks`, or `suspend_tasks` turned off, while owned
  is still started again at the end of the hold. A source removed from the
  file while owning tasks makes Waitarr refuse to start, as for a target.
- The state decoder accepts a stopped task without an execution to
  compare (the host reported none), and refuses a `pending` on any other
  record. Records at rest are not persisted; `tasks.<source>` is written
  even when empty, for the memory of the last activity.
- The policy sees a source as `tasks:<source>`, so its memory cannot clash
  with a target of the same name; the engine splits the memory back.
- The engine reads the tasks only during a hold, while it owns one, or
  while a task seen running during a hold has not ended (to log its end).
  Outside these, the hourly startup check still reads `/ScheduledTasks`
  once an hour, and nothing else.
- The heartbeat message counts the tasks held.
- At load in active mode, a source that is no longer configured and owns
  no task is pruned from the state file; one that owns tasks refuses the
  start (see above).
- A failed read of the tasks is warned about at the first failure, then
  again at most every 10 minutes, like an unreachable service.
- "Seen since" in the log uses Waitarr's clock and is kept in memory
  only.
- After each write, the read back goes through the same pure step
  function as a tick does, so a `stop` stays pending while the task is
  `Cancelling`.

### Crash and race resolution

All of these are decided from what Jellyfin reports, never from time.

- `stop` pending, task `Running` with a different execution: the stop
  landed and a person started it again; the task is yielded.
- `stop` pending, task `Idle` with the same last execution: the execution
  vanished without a result (Jellyfin restarted). The task is owned and
  started again at the end of the hold if nothing ran since, because the
  state found was "running". Residual risk: a read between the switch to
  `Idle` and Jellyfin writing the last result sees the old identity; the
  task is then forgotten without a restart, which is the safe side.
- `stop` pending, task `Idle` with a newer `Cancelled` execution: the stop
  landed, the task is owned.
- `stop` pending, any other status (`Completed`, `Failed`...): the task
  ended by itself and is forgotten.
- `stop` pending, task `Cancelling`: nothing is written; the record is
  kept until the first `Idle`.
- `start` pending when the hold has come back: if the start did not land
  (`Idle`, same execution), the task returns to "stopped" without being
  started; if it landed, it is forgotten, and the next tick stops it like
  any other.
- A stopped task that Jellyfin no longer lists (a plugin removed) is
  forgotten with a warning, and does not count as a failed restore.
