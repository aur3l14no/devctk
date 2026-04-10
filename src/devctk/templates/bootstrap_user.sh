# User setup
container_user=@@USER@@
container_uid=@@UID@@
container_gid=@@GID@@
container_home=@@HOME@@

shell=$(command -v bash 2>/dev/null || echo /bin/sh)

# Ensure log files exist (shadow tools fail without them in rootless containers)
mkdir -p /var/log
touch /var/log/faillog /var/log/lastlog 2>/dev/null || true

# Handle GID
existing_group=$(getent group "$container_gid" 2>/dev/null | cut -d: -f1 || true)
if [ -n "$existing_group" ]; then
    group_name="$existing_group"
elif getent group "$container_user" >/dev/null 2>&1; then
    groupmod -g "$container_gid" "$(getent group "$container_user" | cut -d: -f1)"
    group_name="$container_user"
else
    groupadd -g "$container_gid" "$container_user"
    group_name="$container_user"
fi

# Handle UID
uid_owner=$(getent passwd "$container_uid" 2>/dev/null | cut -d: -f1 || true)
if [ -n "$uid_owner" ] && [ "$uid_owner" != "$container_user" ]; then
    usermod -l "$container_user" -d "$container_home" -m -g "$container_gid" -s "$shell" "$uid_owner"
elif id -u "$container_user" >/dev/null 2>&1; then
    usermod -u "$container_uid" -d "$container_home" -g "$container_gid" -s "$shell" "$container_user"
else
    useradd -M -d "$container_home" -s "$shell" -u "$container_uid" -g "$container_gid" "$container_user"
fi

mkdir -p "$container_home" /etc/sudoers.d
chown "$container_uid:$container_gid" "$container_home" 2>/dev/null || true

# Passwordless sudo
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$container_user" >@@SUDOERS@@
chmod 440 @@SUDOERS@@
