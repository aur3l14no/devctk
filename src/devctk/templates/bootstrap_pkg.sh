# Install sudo if missing.
#
# Use an explicit path instead of `command -v sudo`: when --nix is on, the
# host's /run/current-system/sw/bin is mounted into the container and may
# contain a setuid sudo that can never work under rootless userns. That
# would shadow a real install decision. Checking /usr/bin/sudo directly
# ensures we always put the container's own sudo in place.
if ! [ -x /usr/bin/sudo ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends sudo
fi
