# Nix/mise PATH for interactive shells
mkdir -p /etc/profile.d
cat >/etc/profile.d/99-devctk-nix.sh <<'__NIX__'
@@NIX_PROFILE@@__NIX__
