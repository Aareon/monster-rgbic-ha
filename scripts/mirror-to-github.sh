#!/usr/bin/env bash
# Push a filtered copy of main and the v* tags to the public GitHub mirror.
#
#   scripts/mirror-to-github.sh <git url of the GitHub repo>
#
# Run it from a checkout whose HEAD is the tip of main, with full history and the tags
# (fetch-depth 0). It works on a throwaway clone: the paths in scripts/mirror-exclude.txt are
# removed from every commit with git-filter-repo, then main and the v* tags are pushed WITHOUT
# force. The rewrite is deterministic, so the same Forgejo history always gives the same GitHub
# commit ids and each run is a fast-forward. A rejected push means GitHub moved on its own
# (someone pushed there); stop and look, do not force it.
#
# Commits that never touched an excluded path keep their ids, so a GitHub main that already
# holds the old history is a normal ancestor of the filtered one.
#
# Environment:
#   FILTER_REPO  command that runs git-filter-repo (default: git filter-repo)
#   DRY_RUN=1    do everything except the push (git push --dry-run)
#   GIT_SSH_COMMAND  set by the caller for the deploy key; this script never sees the key.
set -euo pipefail

remote=${1:?usage: mirror-to-github.sh <git url>}
here=$(cd "$(dirname "$0")" && pwd)
src=$(git -C "$here" rev-parse --show-toplevel)
filter_repo=${FILTER_REPO:-git filter-repo}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
work=$tmp/work

git init --quiet "$work"
git -C "$work" fetch --quiet "$src" '+HEAD:refs/heads/main' '+refs/tags/v*:refs/tags/v*'
git -C "$work" checkout --quiet main

# shellcheck disable=SC2086  # FILTER_REPO is a command line on purpose
(cd "$work" && $filter_repo --quiet --force --invert-paths --paths-from-file "$here/mirror-exclude.txt")

# Prove the exclusion held, in the history as well as the tip.
leaked=""
while read -r path; do
  case $path in ''|'#'*) continue ;; esac
  found=$(git -C "$work" log --all --format=%H -1 -- "$path")
  [ -z "$found" ] || leaked="$leaked $path"
done < "$here/mirror-exclude.txt"
if [ -n "$leaked" ]; then
  echo "mirror-to-github: excluded path still present:$leaked" >&2
  exit 1
fi

echo "mirror-to-github: main -> $(git -C "$work" rev-parse --short main)"
extra=()
[ "${DRY_RUN:-}" = 1 ] && extra+=(--dry-run)
git -C "$work" push "${extra[@]}" "$remote" refs/heads/main:refs/heads/main 'refs/tags/v*:refs/tags/v*'
