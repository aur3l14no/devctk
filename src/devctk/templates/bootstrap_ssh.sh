# --- SSH ---
if ! [ -x /usr/sbin/sshd ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends openssh-server
fi

mkdir -p /run/sshd /etc/ssh/authorized_keys /etc/ssh/sshd_config.d
chmod 755 /etc/ssh/authorized_keys
ssh-keygen -A 2>/dev/null

cat >/etc/ssh/sshd_config.d/10-rootless-dev.conf <<'__SSHD__'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
AllowUsers @@USER@@
PidFile /run/sshd.pid
__SSHD__

/usr/sbin/sshd -t
