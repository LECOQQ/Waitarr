# 0014. No throttle ahead of playback from Jellyfin sessions

- Status: accepted (2026-10-31)

## Context

Changing films can take longer than `release_after`: the speed comes
back, the torrents start writing, and the next film starts on a busy
disk. The idea was to treat an open Jellyfin session without playback
(someone browsing the menu) as "a playback soon", and to throttle, or
keep throttling, while it lasts.

Measured against Jellyfin 12.2.0 (a disposable container, a client
signed in as "Jellyfin Android TV"):

- browsing (`/Users/{id}/Views`, `/Items`, `/Items/Latest`,
  `/Users/Me`, an item) never moved the session's `LastActivityDate`;
- only `POST /Sessions/Capabilities/Full` (sent when the app starts)
  and the playback reports (`/Sessions/Playing`, `Progress`, `Stopped`)
  moved it;
- a session stays listed, `IsActive` true, long after its last request,
  so being listed says nothing about someone being there;
- an API key opens no session of its own.

The production server agrees: the living-room session's last activity
was the moment its film stopped, nothing after.

## Decision

No anticipation is built from `/Sessions`. The API shows that an app
was opened and that a playback stopped, never that someone is browsing.
Holding the throttle after a stop is what `release_after` already does;
a household that takes longer to choose the next film raises it
(`WAITARR_RELEASE_AFTER=10m`).

## Consequences

- No new setting and no guess: a throttle still follows a playback.
- To revisit if a Jellyfin version reports browsing (for instance
  through `/Sessions/Viewing`), or for a signal measured against a real
  client, such as the app opening (`Capabilities`) as a short head
  start.
