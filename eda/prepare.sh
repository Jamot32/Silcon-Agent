#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/eda/versions.env"
docker info >/dev/null
docker build --build-arg "LIBRELANE_IMAGE=$LIBRELANE_IMAGE" -t "$EDA_IMAGE" -f "$repo_root/eda/Dockerfile" "$repo_root/eda"
mkdir -p "$repo_root/runs/pdk"
# Provisioning needs network; design execution in check.sh has none.
docker run --rm --cpus 4 --memory 6g \
  -v "$repo_root/runs/pdk:/pdk" "$EDA_IMAGE" \
  ciel fetch --pdk-root /pdk --pdk sky130 --include-libraries default "$SKY130_REVISION"
printf 'EDA image and sky130 PDK prepared. Run make eda-check.\n'
