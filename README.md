# Glowfish Contracts

Versioned cross-repository contracts for Glowfish Reader.

This repository is the single source of truth for:

- `proof.json` compatibility
- OCR worker input, progress, and result data
- account service HTTP endpoints
- local Host HTTP endpoints consumed by the UI

Contracts are additive within a major version. Removing or changing the meaning of an existing field requires a new major version and a migration tool.

## Validate

```powershell
python -m unittest discover -s tests -v
```
