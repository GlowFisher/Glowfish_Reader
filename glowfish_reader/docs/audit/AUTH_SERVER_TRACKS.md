# Authorization Server Tracks (resolved)

Update date: 2026-07-08 — superseded the 2026-07-07 version below.

**Consolidated.** The two parallel tracks this document used to describe (`license_server/` legacy
license-only service, and `user_login_1/server/` account+phone+SMS superset) have been merged:
`user_login_1/server/`'s content now lives at `license_server/` (overwritten in place), and the
legacy license-code activation API (`/activate`, `/deactivate`, `/check`, `/trial`, `issue.py`,
`revoke.py`, `seats.py`) was deleted outright — no license-code customers remained. The
`user_login_1/` directory no longer exists.

`license_server/` now means "the account server that happens to still be named after its
license-code-era origin" (kept for the deployed path `/opt/shupai/license_server`), not "legacy
minimal license service" as the original doc below described.

---

## Original document (2026-07-07, historical)

GlowFish currently contains two server-side authorization tracks. They are not equivalent duplicates.

### Product Direction

The future product direction is the phone-number/member-account system:

- phone registration and password login
- member entitlement and expiry
- SMS verification
- account sessions and usage reporting
- administrator console and audit trail

That direction lived in `../user_login_1/server/` (now merged into `license_server/`, see above).

### Track Roles (historical)

| Track | Role | Notes |
|---|---|---|
| `../user_login_1/server/` | Primary account/member authorization service | Superset track. Included the legacy license activation API plus account, phone, SMS, member, admin, usage, and audit features. |
| `license_server/` | Legacy minimal license service | Small stable server for license token, trial, activation, deactivation, check, and seats. |

### Migration Guidance (historical, executed 2026-07-08)

1. ~~Treat `../user_login_1/server/` as the product target.~~ Done — merged into `license_server/`.
2. ~~Keep `license_server/` as legacy/minimal until switched.~~ Done — old `license_server/` content deleted, replaced.
3. Shared signing helper (`sign.py`) kept; `issue`/`revoke`/`seats` were deleted rather than moved, since the license-code business retired entirely rather than being replaced by an equivalent in the account system.
4. Legacy license endpoints were **not** preserved — confirmed no client still depends on them before deletion.
5. Deployment secrets/private keys/SMS credentials/local SQLite DBs remain out of git, unchanged.
