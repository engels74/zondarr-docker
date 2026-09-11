#!/usr/bin/env bash
set -euo pipefail
arch=${1:?Usage: ./build.sh amd64|arm64}
root=$(cd -- "$(dirname -- "$0")" && pwd)
channel=$(git -C "$root" branch --show-current)
evidence=$(mktemp -d)
python3 "$root/tools/image_metadata.py" --root "$root" --repository edbfi/zondarr-docker --branch "$channel" --revision "$(git -C "$root" rev-parse HEAD)" --arch "$arch" --output "$evidence"
args=()
while IFS= read -r arg; do args+=(--build-arg "$arg"); done < "$evidence/build-args.txt"
docker build -f "$root/linux-$arch.Dockerfile" "${args[@]}" -t "local-validation:$channel-$arch" "$root"
python3 "$root/tools/smoke.py" "local-validation:$channel-$arch" "$evidence" "$arch"
echo "Validation evidence: $evidence"
