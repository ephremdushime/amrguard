#!/bin/sh
set -eu

: "${FUNDER_DEMO_USER:?FUNDER_DEMO_USER is required}"
: "${FUNDER_DEMO_PASSWORD:?FUNDER_DEMO_PASSWORD is required}"

umask 077
htpasswd -bc /etc/nginx/demo.htpasswd "$FUNDER_DEMO_USER" "$FUNDER_DEMO_PASSWORD" >/dev/null
exec "$@"
