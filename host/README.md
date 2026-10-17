# Glowfish Reader Host

Windows integration for the desktop shell, local FastAPI app, document/proof/
export/library services, component assembly, installer, and release website.

Host, UI, OCR, and Contracts are components of a single `Glowfish_Reader_open`
monorepo. Product assembly, integration testing, and Releases live at the
repository root.

For local integration set `GLOWFISH_WORKSPACE_ROOT`, `GLOWFISH_UI_DIST`,
`GLOWFISH_OCR_ROOT`, and `GLOWFISH_CONTRACTS_ROOT`, or run from the monorepo
root where sibling component directories are auto-discovered.

Host-only pull requests run Host boundary and unit tests. Complete product tests
run at the repository root.
