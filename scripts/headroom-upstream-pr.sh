#!/usr/bin/env bash
set -euo pipefail

target=joshyorko/headroom
upstream=headroomlabs-ai/headroom
prefix=patchraptor/upstream-
# Run inside a disposable empty Git repository. Never check out upstream code.
git fetch --quiet --no-tags "https://github.com/$target.git" refs/heads/main:refs/remotes/downstream/main
git fetch --quiet --no-tags "https://github.com/$upstream.git" refs/heads/main:refs/remotes/upstream/main
base=$(git rev-parse refs/remotes/downstream/main)
tip=$(git rev-parse refs/remotes/upstream/main)
common=$(git merge-base "$base" "$tip")
if [[ "$common" == "$tip" ]]; then
  echo "main already contains upstream $tip"
  exit 0
fi

branch="$prefix$tip"
# A reviewer may have added conflict resolutions. Leave that entire PR alone.
open=$(gh api --paginate "repos/$target/pulls?state=open&base=main&per_page=100" \
  --jq '.[] | select(.head.repo.full_name == "joshyorko/headroom" and (.head.ref | startswith("patchraptor/upstream-"))) | .html_url')
if [[ -n "$open" ]]; then
  echo "Review already open: $open"
  exit 0
fi
previous=$(gh api "repos/$target/pulls?state=closed&base=main&head=joshyorko:$branch" --jq '.[0].html_url // empty')
if [[ -n "$previous" ]]; then
  echo "Snapshot already reviewed: $previous"
  exit 0
fi

# A same-repository branch can trigger Actions before review. Keep the trusted
# workflows on it, including downstream CI. The PR links the upstream workflow diff.
git read-tree "$tip"
git rm --quiet -r --cached --ignore-unmatch .github/workflows
git read-tree --prefix=.github/workflows/ "$base:.github/workflows"
tree=$(git write-tree)
git config user.name 'patchraptor[bot]'
git config user.email 'patchraptor[bot]@users.noreply.github.com'
snapshot=$(git commit-tree "$tree" -p "$tip" -m "chore: retain downstream workflows for upstream review")
remote="https://github.com/$target.git"
existing=$(git ls-remote "$remote" "refs/heads/$branch")
if [[ -z "$existing" ]]; then
  git push "$remote" "$snapshot:refs/heads/$branch"
else
  # Recover a successful push followed by a failed PR creation.
  git fetch --quiet --no-tags "$remote" "refs/heads/$branch"
  [[ "$(git rev-parse FETCH_HEAD^)" == "$tip" && "$(git rev-parse FETCH_HEAD^{tree})" == "$tree" ]] || {
    echo "Existing snapshot branch differs; leaving it intact." >&2
    exit 1
  }
fi

gh api "repos/$target/pulls" -f head="$branch" -f base=main -F draft=true \
  -f title="chore: review upstream Headroom ${tip:0:12}" \
  -f body="Upstream snapshot: https://github.com/$upstream/commit/$tip

Resolve conflicts on this branch. Use a merge commit to retain upstream ancestry. This PR keeps downstream GitHub Actions workflows. Review upstream workflow changes separately with \`git diff $common $tip -- .github/workflows\` after fetching upstream." \
  --jq .html_url
