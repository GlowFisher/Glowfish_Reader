# Security Policy

- Never embed account secrets, signing keys, deployment credentials, user data, or source documents.
- All Host calls go through `src/api/`.
- Authentication UI must not log phone numbers, passwords, cookies, or complete server responses.
- Keep the login modal before the auth guard in script order.
