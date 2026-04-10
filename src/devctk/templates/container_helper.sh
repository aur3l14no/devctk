#!/bin/sh
set -eu

podman=@@PODMAN@@
name=@@NAME@@

create() {
    if "$podman" container exists "$name"; then exit 0; fi
    exec @@CREATE_CMD@@
}

start() {
    running=$("$podman" inspect -f '{{.State.Running}}' "$name" 2>/dev/null || printf 'false\n')
    if [ "$running" = "true" ]; then exec "$podman" attach "$name"; fi
    exec "$podman" start --attach "$name"
}

stop() {
    exec "$podman" stop --ignore -t 10 "$name"
}

case "${1:-}" in
    create) create ;; start) start ;; stop) stop ;;
    *) echo "usage: $0 {create|start|stop}" >&2; exit 2 ;;
esac
