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
- Issues: read and write
- Pull requests: read and write
- Workflows: read and write
- Metadata: read-only

Then set these repository secrets on `joshyorko/renovate-config`:

- `RENOVATE_APP_ID`
- `RENOVATE_PRIVATE_KEY`

Example:

```bash
gh secret set RENOVATE_APP_ID --repo joshyorko/renovate-config --body "<app-id>"
gh secret set RENOVATE_PRIVATE_KEY --repo joshyorko/renovate-config < /path/to/dudley-bot.private-key.pem
```
