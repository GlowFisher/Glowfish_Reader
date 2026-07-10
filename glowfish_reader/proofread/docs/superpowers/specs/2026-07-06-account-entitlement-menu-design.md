# Account Entitlement Menu Design

## Goal

Replace the current top-right user chip with a lightweight account menu that shows the logged-in user's entitlement state and provides logout.

This first version intentionally avoids membership purchase, activation-code entry, user-center pages, device management, or marketing actions. It is only an account status surface.

## User Experience

The top-right toolbar shows a compact account button:

- Trial account: `张三 · 试用`
- Member account: `张三 · 会员`

Clicking the button opens a small popover anchored below the account button.

Trial popover:

```text
张三
试用有效期至 2026-08-31

退出登录
```

Member popover:

```text
张三
会员有效期至 2026-08-31

退出登录
```

The popover closes when the user clicks outside it, presses Esc, or clicks logout.

## Data Contract

The frontend should rely on account data returned by the authenticated user endpoint rather than calculating entitlement state locally.

Minimum shape:

```json
{
  "username": "zhangsan",
  "display": "张三",
  "entitlement": {
    "mode": "trial",
    "expires_at": "2026-08-31"
  }
}
```

Supported entitlement modes for this version:

- `trial`: render `试用有效期至 YYYY-MM-DD`
- `member`: render `会员有效期至 YYYY-MM-DD`

If `display` is missing, fall back to `username`. If entitlement data is missing or unrecognized, keep the account button usable and show only the user name plus logout.

## UI Placement

Use the existing top-right `userChip` area. Replace the inline `用户名 + 登出` layout with:

- one compact button for account summary
- one hidden popover for the full status and logout action

The account button should match the existing toolbar's restrained visual style and should not compete with search, notice, or settings icons.

## Behavior

Logout keeps the existing behavior:

- clear the remembered user identity
- clear local cache if the current logout path already does so
- redirect to the login page

No entitlement enforcement is included in this design. Trial expiration handling and paid membership workflows are explicitly future work.

## Testing

Manual checks:

- trial account renders `张三 · 试用` in the toolbar and `试用有效期至 2026-08-31` in the popover
- member account renders `张三 · 会员` in the toolbar and `会员有效期至 2026-08-31` in the popover
- logout still works from the popover
- click-outside and Esc close the popover
- missing entitlement data does not break login display or logout

