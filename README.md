# Patchraptor Renovate Config

Central self-hosted Renovate runner for Dudley repositories.

This follows the Project Bluefin pattern:

- `renovate-config.json` is the self-hosted runner config.
- `org-inherited-config.json` is inherited by discovered repositories.
- `.github/workflows/renovate.yml` mints a GitHub App installation token and runs Renovate.

Patchraptor runs every 30 minutes. Dependency Dashboard checkbox edits in target
repositories are processed on the next central run or after a manual workflow
dispatch in this repo.

The Renovate workflow also supports a `qualification-only` manual dispatch
input. Enable it to qualify the existing Review OMP update from a selected
central branch without running Renovate or writing qualification receipts.
When the trusted Review PR base contains both `ci/sdk-types/package.json` and
`ci/sdk-types/package-lock.json`, qualification reproduces the SDK lock from
that base with its pinned Node/npm toolchain. Older bases without either file
retain the Containerfile-only qualification contract; a partial base pair fails.

Patchraptor uses `patchraptor/` for Renovate branch names. Project Bluefin's bot
identity is branded, but its live dependency PR branches still use Renovate's
default `renovate/` prefix; this config keeps the branch names branded too.

## GitHub App setup

Create a GitHub App named `Patchraptor`, install it on:

- `joshyorko/camp`
- `joshyorko/codex-action-server`
- `joshyorko/devsy-provider-harvester`
- `joshyorko/renovate-config`
- `joshyorko/review`
- `joshyorko/dsb-common`
- `joshyorko/dudley-factory`
- `joshyorko/dudley-os`
- `joshyorko/homebrew-tools`
- `joshyorko/mcp-tunnel-kit`
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

Verify the Patchraptor App installation includes both new repositories with
these permissions before the first scheduled run. The central discovery
allowlist does not grant App access by itself.

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

## Codex control-plane repositories

Patchraptor discovers `codex-action-server` and `mcp-tunnel-kit` from the
explicit allowlist above. It uses Renovate's standard Python, GitHub Actions,
and Containerfile managers for CAS dependencies. The pinned `devsy`, `kubectl`,
and `actions-runtime` downloads combine versions with independent SHA256
checksums; they stay out of generic version-only updates until a paired
checksum refresh can be reproduced safely. CAS RCC release qualification and
method approval belong to [codex-action-server issue #25](https://github.com/joshyorko/codex-action-server/issues/25),
not to Patchraptor.

In tunnel-kit, Renovate tracks the `executor` and `tunnel` production image
tag+digest pairs in `config/deploy-images.json` and the matching Compose image
references. Those updates require a Dependency Dashboard checkbox and passing
repository CI before Renovate opens a PR; they are never automerged. The CAS
and schema-proxy image entries share a CAS digest and source revision and are
excluded from generic image updates. Only the provenance-verified CAS handoff
in [mcp-tunnel-kit issue #64](https://github.com/joshyorko/mcp-tunnel-kit/issues/64)
may change them. Human review and the repository's protected deployment workflow
remain required; Patchraptor does not deploy or restart native daemons.
