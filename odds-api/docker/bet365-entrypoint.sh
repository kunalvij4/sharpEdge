#!/bin/sh
set -eu

# Keep the display alive until the worker has finished graceful browser cleanup.
bet365_worker_pid=
bet365_xvfb_pid=
bet365_auth=$(mktemp /tmp/bet365-xauth.XXXXXX)

bet365_cleanup() {
    trap - TERM INT EXIT
    if [ -n "$bet365_worker_pid" ]; then
        kill -TERM "$bet365_worker_pid" 2>/dev/null || true
        wait "$bet365_worker_pid" 2>/dev/null || true
    fi
    if [ -n "$bet365_xvfb_pid" ]; then
        kill -TERM "$bet365_xvfb_pid" 2>/dev/null || true
        wait "$bet365_xvfb_pid" 2>/dev/null || true
    fi
    rm -f "$bet365_auth"
}
trap 'bet365_cleanup; exit 0' TERM INT
trap bet365_cleanup EXIT

bet365_display_number=99
while [ -e "/tmp/.X${bet365_display_number}-lock" ] || [ -S "/tmp/.X11-unix/X${bet365_display_number}" ]; do
    bet365_display_number=$((bet365_display_number + 1))
done
export DISPLAY=":${bet365_display_number}"
export XAUTHORITY="$bet365_auth"
bet365_cookie=$(python -c 'import secrets; print(secrets.token_hex(16))')
xauth -f "$XAUTHORITY" add "$DISPLAY" . "$bet365_cookie"
unset bet365_cookie
Xvfb "$DISPLAY" -screen 0 1600x1100x24 -nolisten tcp -auth "$XAUTHORITY" >/tmp/bet365-xvfb.log 2>&1 &
bet365_xvfb_pid=$!
bet365_attempt=0
while [ ! -S "/tmp/.X11-unix/X${bet365_display_number}" ]; do
    bet365_attempt=$((bet365_attempt + 1))
    if ! kill -0 "$bet365_xvfb_pid" 2>/dev/null || [ "$bet365_attempt" -gt 100 ]; then
        cat /tmp/bet365-xvfb.log >&2
        exit 1
    fi
    sleep 0.1
done

"$@" &
bet365_worker_pid=$!
bet365_exit=0
wait "$bet365_worker_pid" || bet365_exit=$?
bet365_worker_pid=
exit "$bet365_exit"
