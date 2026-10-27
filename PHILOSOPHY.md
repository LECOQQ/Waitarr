# 🧭 Philosophy

## 🌱 Why Waitarr exists

My NAS is a Raspberry Pi 4 with USB drives. They are WD_BLACK P10s,
shingled (SMR) disks behind a USB bridge that speaks "Bulk-Only": one
request at a time, no queue. Alone, a drive reads fast enough for
anything. Two reads at once, and throughput collapses to around two
megabytes per second.

That is exactly what happens when Jellyfin plays a film while
qBittorrent seeds from the same disk. The torrent wins, and the film
freezes.

The usual answer is more hardware: a real NAS, a SATA controller, an
SSD cache. The answer I prefer is software that knows what the hardware
cannot do, and gets out of the way.

> **Modest hardware, compensated by careful software.**

## 🎯 What Waitarr is

Waitarr watches what plays, and while something does, it slows
qBittorrent to a trickle. When the playback has been over for a few
minutes, it gives the speed back -- exactly as it found it.

It does not pause torrents. Pausing drops every peer and re-announces on
resume. A torrent held at a kilobyte per second stays connected, keeps
its place in the swarm, and seeds again at full speed the moment the
film ends.

## 🙋 A human decision is never overwritten

If you turned the turtle on yourself, Waitarr leaves it on. If you change
it while Waitarr holds it, Waitarr steps aside until the playback is
over. It only ever undoes its own change, and it remembers what that
change was, across crashes and restarts.

## 🔭 Observe before acting

A tool that writes to your torrent client should first show you what it
would do. Waitarr starts in observation mode, and in that mode it cannot
write: not "does not", cannot. Switching to active mode is a decision you
make after reading the log.

## 🧯 When in doubt, do nothing

If Jellyfin does not answer, Waitarr does not know whether something is
playing, so it changes nothing. If qBittorrent does not answer, Waitarr
cannot know its state, so it changes nothing there either. It says so,
and tells you if you asked it to.

## 💽 Where it is going

The disk is the point, not the bandwidth. Version 1 throttles every
torrent while anything plays. The next step is to throttle only the
torrents that live on the disk being read, and to listen to more than
Jellyfin: Audiobookshelf, Plex, Emby.

## ✅ A simple test for new features

A feature belongs in Waitarr if it helps **a playback get the disk it
needs, without taking anything from the torrents that it does not give
back**.
