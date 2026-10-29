#!/usr/bin/env bash
set -euo pipefail
image=$1
evidence=$2
mkdir -p "$evidence"
evidence=$(realpath "$evidence")
chmod 777 "$evidence"
docker create --name remedy-html-proof --init --network none --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --security-opt "seccomp=$PWD/deploy/chromium-seccomp-amd64.json" \
  --shm-size=256m --stop-timeout 20 \
  --mount "type=bind,src=$evidence,dst=/evidence" \
  --env REMEDY_SANDBOX_AUDIT_DIR=/evidence "$image"
sudo python3 .github/scripts/chromium-observer.py remedy-html-proof "$evidence" > "$evidence/observer.log" 2>&1 &
observer=$!
finish() {
  status=$?
  trap - EXIT
  set +e
  docker stop --time 20 remedy-html-proof >/dev/null
  stop_status=$?
  touch "$evidence/observer-stop"
  wait "$observer"
  observer_status=$?
  docker logs remedy-html-proof > "$evidence/runtime.log" 2>&1
  logs_status=$?
  docker inspect remedy-html-proof > "$evidence/container.json"
  inspect_status=$?
  for outcome in "$status" "$stop_status" "$observer_status" "$logs_status" "$inspect_status"; do
    if [ "$outcome" -ne 0 ]; then exit "$outcome"; fi
  done
}
trap finish EXIT
timeout 900s docker start --attach remedy-html-proof
test "$(docker inspect --format '{{.State.ExitCode}}' remedy-html-proof)" = 0
for tool in render axe pa11y lighthouse; do test -s "$evidence/sandbox-$tool.json"; done
