#!/bin/sh
# Seed only public CA trust; the unchanged renderer keeps TLS and sandbox checks.
set -eu
[ "$(id -u)" -ne 0 ]
[ "${HOME:-}" = /tmp/renderer-home ]
[ "$#" -gt 0 ]
umask 077
for name in cert9.db key4.db; do
  [ -f "/run/certificates/nss-seed/$name" ]
  [ ! -L "/run/certificates/nss-seed/$name" ]
done
for database in "$HOME/.pki/nssdb" "$HOME/.local/share/pki/nssdb"; do
  [ ! -e "$database" ]
  [ ! -L "$database" ]
  mkdir -p "$database"
  cp /run/certificates/nss-seed/cert9.db "$database/cert9.db"
  cp /run/certificates/nss-seed/key4.db "$database/key4.db"
done
exec "$@"
