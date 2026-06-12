#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

if ! command -v fzf >/dev/null 2>&1; then
  echo "fzf が見つかりません。mise などで fzf をインストールしてください。" >&2
  exit 1
fi

running_containers="$(
  docker ps \
    --filter "label=com.docker.compose.project.working_dir=$REPO_ROOT" \
    --filter "label=com.docker.compose.oneoff=False" \
    --format '{{.Label "com.docker.compose.service"}}	{{.Names}}	{{.Status}}'
)"

if [[ -z "$running_containers" ]]; then
  echo "この repo の Docker Compose で起動中のコンテナはありません。"
  exit 0
fi

selection="$(
  printf '%s\n' "$running_containers" | fzf \
    --prompt='restart container> ' \
    --header='SERVICE	CONTAINER	STATUS' \
    --delimiter=$'\t' \
    --with-nth=1,2,3 \
    --height=40% \
    --reverse \
    --exit-0
)"

if [[ -z "$selection" ]]; then
  echo "キャンセルしました。"
  exit 0
fi

IFS=$'\t' read -r service container _status <<< "$selection"

echo "Restarting $container ($service) without rebuild..."
docker compose stop "$service"
docker compose rm --force "$service"
docker compose up -d --no-build --no-deps "$service"
docker compose ps "$service"
