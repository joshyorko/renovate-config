# Patchraptor Renovate Config

Central self-hosted Renovate runner for Dudley repositories.

This follows the Project Bluefin pattern:

- `renovate-config.json` is the self-hosted runner config.
- `org-inherited-config.json` is inherited by discovered repositories.
- `.github/workflows/renovate.yml` mints a GitHub App installation token and runs Renovate.

Patchraptor runs every 30 minutes. Dependency Dashboard checkbox edits in target
repositories are processed on the next central run or after a manual workflow
dispatch in this repo.

Patchraptor uses `patchraptor/` for Renovate branch names. Project Bluefin's bot
identity is branded, but its live dependency PR branches still use Renovate's
default `renovate/` prefix; this config keeps the branch names branded too.

## GitHub App setup

Create a GitHub App named `Patchraptor`, install it on:

- `joshyorko/renovate-config`
- `joshyorko/dsb-common`
- `joshyorko/dudley-factory`
- `joshyorko/dudley-os`
- `joshyorko/homebrew-tools`
- `joshyorko/rcc`
- `joshyorko/room-of-requirement`

Repository permissions:

- Administration: read-only
- Checks: read and write
- Contents: read and write
- Dependabot alerts / vulnerability alerts: read-only
- Issues: read and write
- Pull requests: read and write
- Commit statuses: read and write
- Workflows: read and write
- Metadata: read-only

Then set these repository secrets on `joshyorko/renovate-config`:

- `RENOVATE_CLIENT_ID`
- `RENOVATE_PRIVATE_KEY`

Example:

```bash
gh secret set RENOVATE_CLIENT_ID --repo joshyorko/renovate-config --body "<client-id>"
gh secret set RENOVATE_PRIVATE_KEY --repo joshyorko/renovate-config < /path/to/dudley-bot.private-key.pem
```

## Dagger modules

Patchraptor detects Dagger module dependencies in `.dagger/go.mod`, but does not
open Renovate Go module PRs for that file. Dagger generates `internal/dagger`
with `dagger develop`, and Renovate's generic Go artifact update runs
`go get -t ./...` without that generated package present.

## Dashboard warnings

If a target repository dashboard says `Cannot access vulnerability alerts`, the
Patchraptor GitHub App installation is missing `Dependabot alerts: read-only`
access. The repository can still receive normal dependency PRs, but Renovate
cannot read GitHub vulnerability alerts until the App permissions are updated
and the installation accepts the new permission request.
