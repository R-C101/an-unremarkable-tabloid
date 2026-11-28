# Help bring An Unremarkable Tabloid to the Paper Pro (and more reMarkable 2 software versions)

It's been tested on a **reMarkable 1** and a **reMarkable 2**, both on software 3.29. Everything on the
computer side (rendering, pairing, scheduling) carries over. What's missing on the Paper Pro is the last step:
**drawing a PNG on the screen**, and maybe sleep.

If you have a Paper Pro or Paper Pro Move and a little technical curiosity (or a coding agent like Claude Code,
Codex or Cursor), you can probably get it working in an evening. Please share what you find, even if it's only
"here's what `tabloid tablet info` says". If you have an rM2 on a different software version, a note saying
whether it works is just as useful.

## What's different

| | reMarkable 1 (works) | reMarkable 2 (works) | Paper Pro / Move |
|---|---|---|---|
| CPU | 32-bit ARM (armv7) | 32-bit ARM (armv7) | 64-bit ARM (aarch64) |
| SSH | Built in | Built in, same password screen | Only in **developer mode**, which **factory-resets** the tablet |
| Screen | Normal framebuffer `/dev/fb0` + refresh ioctl | `/dev/fb0` is only a raw buffer; the panel is driven in software, normally by xochitl | Colour panel; different display stack |
| Display program | `device/main.go` → `tabloid-show-armv7` | `device/rm2` → `tabloid-show-rm2-armv7`, on the swtcon driver from rM2-stuff | Needs an aarch64 build and a new way to draw |
| Sleep | `echo mem > /sys/power/state` | Must go through systemd (`systemctl start suspend.target`) or Wi-Fi dies | Unknown |

The reMarkable 2 port is a worked example of the steps below: its notes are in CLAUDE.md under "Hardware facts"
and "Battery and sleep".

## Ground rules (please keep these)

Read the "Tablet safety rules" in [CLAUDE.md](../CLAUDE.md#tablet-safety-rules-do-not-relax) first. In short:

- Back up first: `uv run tabloid tablet backup`.
- Write only inside `/home/root/tabloid`. No changes to `/usr`, `/etc`, the root filesystem or the bootloader,
  and no persistent system services. A reboot must always bring back the normal tablet.
- Prefer approaches that don't need Toltec/XOVI or other system mods. If something truly needs them, open an issue
  to discuss it first.
- On a Paper Pro, turning on developer mode **erases the tablet**. Sync your notebooks to the cloud first and only do it
  if you're comfortable with that.

## The quick way: let a coding agent do it

1. Clone the repo, run `uv sync`, put your tablet's IP and SSH password in `.env` (see the README).
2. Open the folder in Claude Code (or another agent) and paste:

> I have a **reMarkable Paper Pro** (or: Paper Pro Move). This project only supports the reMarkable 1 and 2. Read
> CLAUDE.md, docs/porting.md, device/main.go and unremarkable/device.py. Follow the tablet safety rules strictly
> and back up my notebooks before touching anything. First, connect over SSH and investigate read-only: model,
> architecture, firmware, kernel, framebuffer devices, how xochitl draws to the screen, and whether suspend and the
> RTC wake alarm work. Tell me what you find and propose an approach before changing anything on the tablet.
> Then add support in a way that keeps the reMarkable 1 working: detect the model in `device.unsupported()` and
> `Tablet.install()`, build any new binary into unremarkable/bin/, and document what you verified in CLAUDE.md
> ("Hardware facts") and in the README table "Which reMarkable?".

3. Check it on your tablet: `uv run tabloid push`, then a restart to make sure the normal UI comes back.
4. Open a pull request, or just an issue with your notes. Notes alone are a big help.

## Useful things to report

```sh
uv run tabloid tablet info        # model, firmware, architecture, battery, Wi-Fi IP
```

Plus, from an SSH session on the tablet: `ls -l /dev/fb*`, `cat /sys/class/graphics/fb0/name`,
`cat /sys/power/mem_sleep`, `ls /sys/class/rtc`. Don't post your password or IP address.

## Questions

Open an issue with the "Help support my tablet" template, or message the author. Happy to help over chat or a call.
