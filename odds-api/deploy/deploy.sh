#!/usr/bin/env bash
# Invoked by GitHub Actions; registry token and optional Redis URL arrive as stdin lines.
set -Eeuo pipefail
umask 077

die() { printf '%s\n' "$*" >&2; exit 1; }

[[ $# == 4 ]] || die 'Usage: deploy.sh DEPLOY_DIR IMAGE_DIGEST REGISTRY_USER COMPOSE_PROJECT'
deploy_dir=$1
image=$2
registry_user=$3
project=$4
[[ "$deploy_dir" =~ ^/[a-zA-Z0-9_./-]+$ && "$deploy_dir" != / && "$deploy_dir" != */ ]] || die 'Invalid deployment directory.'
[[ "/$deploy_dir/" != */../* && "/$deploy_dir/" != */./* ]] || die 'Invalid deployment path segments.'
[[ "$image" =~ ^ghcr.io/[a-z0-9_./-]+@sha256:[0-9a-f]{64}$ ]] || die 'Deploy an image pinned by its GHCR sha256 digest.'
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die 'Invalid Compose project name.'
[[ -f "$deploy_dir/.env" ]] || die "Missing $deploy_dir/.env. Copy the existing API configuration there before deploying."
command -v flock >/dev/null || die 'Install flock (util-linux) on the server.'
release_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
canonical_dir=$(cd -- "$deploy_dir" && pwd -P)
[[ "$release_dir" == "$canonical_dir"/releases/* ]] || die 'Run the script from a release inside DEPLOY_DIR/releases.'
[[ -f "$release_dir/compose.yaml" ]] || die 'Release compose.yaml is missing.'

# Also serialize deployments started outside GitHub Actions.
exec 9>"$deploy_dir/.deploy.lock"
flock -n 9 || die 'Another deployment is already running.'

# Do not source .env: credentials may contain shell metacharacters.
IFS= read -r registry_token || die 'Missing registry token on stdin.'
redis_url=''
IFS= read -r redis_url || true
if ! grep -Eq '^[[:space:]]*(export[[:space:]]+)?REDIS_URL[[:space:]]*=' "$deploy_dir/.env"; then
  [[ "$redis_url" == rediss://* || "$redis_url" == redis://* ]] || die 'REDIS_URL is missing from .env; set GitHub secret ODDS_REDIS_URL.'
  [[ "$redis_url" != *"'"* && "$redis_url" != *$'\r'* ]] || die 'URL-encode quotes and control characters in ODDS_REDIS_URL.'
  chmod 600 "$deploy_dir/.env"
  # Single quotes prevent Compose interpolation of dollar signs in credentials.
  printf "\nREDIS_URL='%s'\n" "$redis_url" >> "$deploy_dir/.env"
fi
unset redis_url

export ODDS_API_IMAGE="$image"
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
cleanup() {
  result=$?
  trap - EXIT
  rm -rf -- "$DOCKER_CONFIG"
  if (( result != 0 )); then
    printf 'Deployment failed; current still identifies the last successful release. Inspect the Compose services before retrying.\n' >&2
  fi
  exit "$result"
}
trap cleanup EXIT

compose() {
  docker compose --project-name "$project" --env-file "$deploy_dir/.env" --file "$release_dir/compose.yaml" "$@"
}

# Validate configuration and pull everything before stopping the existing API.
compose config --quiet
printf '%s\n' "$registry_token" | docker login ghcr.io --username "$registry_user" --password-stdin
unset registry_token
compose pull api
# Remove former SQL services without deleting their data volumes.
compose up --no-build --remove-orphans --force-recreate --wait --wait-timeout 120 api

# --wait uses compose.yaml's /health/ready probe. Only mark healthy releases current.
printf '%s\n' "$image" > "$release_dir/image"
previous=$(readlink -- "$deploy_dir/current" || true)
if [[ -n "$previous" && "$previous" != "$release_dir" ]]; then
  ln -sfn -- "$previous" "$deploy_dir/previous"
fi
ln -sfn -- "$release_dir" "$deploy_dir/current"
printf 'Deployment healthy: %s\n' "$image"
