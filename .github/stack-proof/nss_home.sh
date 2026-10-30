#!/bin/sh
# Isolated CI trust setup only; the unchanged product keeps TLS validation on.
set -eu
case "$HOME" in /tmp/renderer-home|/tmp/renderer-rebased-home) ;; *) exit 1 ;; esac
rebase=false
if [ "${1:-}" = --rebase-config ]; then rebase=true; shift; fi
umask 077
for database in "$HOME/.pki/nssdb" "$HOME/.local/share/pki/nssdb"; do
  [ ! -e "$database" ]
  mkdir -p "$database"
  # NSS initializes its location-dependent module configuration here. Do not
  # copy the host's pkcs11.txt, which can contain host-specific paths.
  cp /fixture-nss/cert9.db "$database/cert9.db"
  cp /fixture-nss/key4.db "$database/key4.db"
  if [ "$rebase" = true ]; then
    sed "s@configdir='[^']*'@configdir='sql:$database'@g" /fixture-nss/pkcs11.txt > "$database/pkcs11.txt"
  fi
done
exec "$@"
