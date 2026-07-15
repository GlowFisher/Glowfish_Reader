# Security Policy

- OCR source images and user documents must never leave the local machine.
- Model binaries, caches, user output, and credentials must not enter Git.
- A release build may use a model only when its path, byte size, and SHA-256 match `models.lock.json`.
- Model download or replacement is a release operation, never a recognition-time fallback.
