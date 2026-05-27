# Patchraptor Renovate Config

Central self-hosted Renovate runner for Dudley repositories.

This follows the Project Bluefin pattern:

- `renovate-config.json` is the self-hosted runner config.
- `org-inherited-config.json` is inherited by discovered repositories.
- `.github/workflows/renovate.yml` mints a GitHub App installation token and runs Renovate.

Patchraptor runs every 30 minutes. Dependency Dashboard checkbox edits in target
repositories are processed on the next central run or after a manual workflow
dispatch in this repo.

## GitHub App setup

Create a GitHub App named `Patchraptor`, install it on:

- `joshyorko/renovate-config`
- `joshyorko/dsb-common`
- `joshyorko/dudley-os`

Repository permissions:

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
