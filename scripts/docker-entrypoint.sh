#!/usr/bin/env bash
set -e

export SURF_HOST="${SURF_HOST:-0.0.0.0}"
export DISPLAY="${DISPLAY:-:99}"

if [ "${SURF_ENABLE_XVFB:-true}" = "true" ] && command -v Xvfb >/dev/null 2>&1; then
    if ! [ -e /tmp/.X99-lock ]; then
        Xvfb :99 -screen 0 1920x1080x24 +extension RANDR >/tmp/xvfb.log 2>&1 &
    fi
fi

exec "$@"
