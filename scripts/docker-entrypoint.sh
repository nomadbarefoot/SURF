#!/usr/bin/env bash
set -e

export SURF_HOST="${SURF_HOST:-0.0.0.0}"
export DISPLAY="${DISPLAY:-:99}"

if [ "$SURF_AUTH_MODE" = "token" ] && [ -z "$SURF_API_TOKEN" ]; then
    echo "ERROR: SURF_AUTH_MODE=token requires SURF_API_TOKEN to be set." >&2
    exit 1
fi

if [ "$SURF_AUTH_MODE" = "loopback" ] && [ "$SURF_HOST" != "127.0.0.1" ] && [ "$SURF_HOST" != "localhost" ]; then
    echo "ERROR: SURF_AUTH_MODE=loopback is only allowed on loopback hosts. Use token auth for $SURF_HOST." >&2
    exit 1
fi

if [ "${SURF_ENABLE_XVFB:-true}" = "true" ] && command -v Xvfb >/dev/null 2>&1; then
    if ! [ -e /tmp/.X99-lock ]; then
        Xvfb :99 -screen 0 1920x1080x24 +extension RANDR >/tmp/xvfb.log 2>&1 &
    fi
fi

exec "$@"
