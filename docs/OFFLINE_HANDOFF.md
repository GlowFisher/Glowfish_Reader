# Offline repository handoff

Codex does not need GitHub access. The five repositories are delivered as verified Git
bundles and can be hosted in any of these ways:

1. **Preferred:** a maintainer runs `publish_private_repos.ps1` on a separately
   authenticated workstation. No token is copied into this workspace.
2. **Private LAN:** run `initialize_local_remotes.ps1` against an access-controlled SMB
   share. Developers clone/push normally; review approval is recorded manually.
3. **Self-hosted forge:** import the five bundles into Gitea, GitLab, Azure DevOps, or
   Bitbucket and apply the branch rules from `CONTRIBUTING.md`/`CODEOWNERS`.

## Restore bundles

Place all bundles in one directory and run:

```powershell
git clone .\glowfish-contracts.bundle glowfish-contracts
git clone .\glowfish-reader-ui.bundle glowfish-reader-ui
git clone .\glowfish-ocr.bundle glowfish-ocr
git clone .\glowfish-account.bundle glowfish-account
git clone .\glowfish-reader-host.bundle glowfish-reader-host
Set-Location .\glowfish-reader-host
git switch integration/2.0
git -c protocol.file.allow=always submodule update --init --recursive
python scripts\validate_components.py
```

Verify `SHA256SUMS.txt` before cloning. Keep the bundle set immutable; create a new
dated export for later updates.

## Required server-side controls

For every `main` branch: block direct pushes and force pushes, require one non-author
approval, dismiss stale approvals, require resolved conversations and CI, apply
CODEOWNERS, and prevent branch deletion. Protect release tags. Host is the only repo
allowed to run installer signing/publishing credentials.
