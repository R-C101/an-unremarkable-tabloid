#!/bin/sh
# rmdash sleep loop: runs on the tablet so it sleeps between refreshes.
#
# The tablet stays awake for AWAKE seconds after every EVERY-second boundary
# of local time (e.g. :00 and :30), so the computer can push a new image.
# The rest of the time it is in deep sleep ("mem"), drawing almost nothing.
# E-ink keeps showing the last image while it sleeps.
#
# Started by rmdash as a transient systemd unit (systemd-run), so it never
# survives a reboot: restarting the tablet always brings back the normal UI.
# Nothing here writes outside /home/root/rmdash, apart from the kernel's own
# runtime switches (/sys/class/rtc/rtc0/wakealarm, /sys/power/state).
#
# Files the computer may leave in DIR:
#   offset  the computer's UTC offset in seconds, so windows follow local time
#   busy    a push is in progress: don't sleep (ignored once 5 minutes old)
#   hold    stay awake until it is removed (maintenance)

DIR=/home/root/rmdash
EVERY=${1:-1800}
AWAKE=${2:-180}
RTC=/sys/class/rtc/rtc0/wakealarm

fresh() { [ -e "$1" ] && [ $(( $(date +%s) - $(stat -c %Y "$1") )) -lt 300 ]; }

while true; do
  now=$(date +%s)
  off=$(cat "$DIR/offset" 2>/dev/null || echo 0)
  into=$(( (now + off) % EVERY ))
  if [ -e "$DIR/hold" ] || fresh "$DIR/busy"; then
    sleep 10; continue
  fi
  if [ "$into" -lt "$AWAKE" ]; then  # inside the awake window: wait it out
    sleep $(( AWAKE - into )); continue
  fi
  wake=$(( EVERY - into ))
  echo 0 > "$RTC"
  echo "+$wake" > "$RTC"
  fresh "$DIR/busy" && continue  # a push started just now
  echo mem > /sys/power/state || sleep 30   # returns after waking (alarm or power button)
  sleep 15                      # give Wi-Fi a moment before deciding again
done
