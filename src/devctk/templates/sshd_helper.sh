#!/bin/sh
set -eu

podman=@@PODMAN@@
name=@@NAME@@

stop_sshd() {
    "$podman" exec --user root "$name" /bin/sh -c \
        'if [ -f /run/sshd.pid ]; then kill "$(cat /run/sshd.pid)" 2>/dev/null; fi' || true
}

start() {
    # Wait for bootstrap to finish
    n=0
    while ! "$podman" exec "$name" test -f /run/devctk-ready 2>/dev/null; do
        n=$((n + 1))
        if [ "$n" -ge 120 ]; then
            echo "container $name bootstrap not ready after 120s" >&2
            exit 1
        fi
        sleep 1
    done

    stop_sshd
    exec "$podman" exec --user root "$name" /usr/sbin/sshd -D -e -o PidFile=/run/sshd.pid
}

stop() {
    stop_sshd
}

case "${1:-}" in
    start) start ;; stop) stop ;;
    *) echo "usage: $0 {start|stop}" >&2; exit 2 ;;
esac
