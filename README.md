# Glowfish Reader Host

Windows integration repository for the desktop shell, local FastAPI app,
document/proof/export/library services, component assembly, installer, and release
website.

Host does not own UI, OCR, or Contracts repositories. Product assembly,
component commit locking, integration testing, and Releases belong to the
`Glowfish_Reader` workspace repository.

For local integration set `GLOWFISH_WORKSPACE_ROOT`, `GLOWFISH_UI_DIST`,
`GLOWFISH_OCR_ROOT`, and `GLOWFISH_CONTRACTS_ROOT`, or place this repository next
to the other module worktrees.

Host-only pull requests run Host boundary and unit tests. Complete product tests
run in the total workspace repository.
