# Microsoft Entra ID setup

LibreChat signs people in with OpenID Connect against Entra ID. Multi-factor
sign-in, who may use the app, and offboarding are all controlled in Entra ID.

## 1. App registration

1. **Entra admin center → App registrations → New registration.** Name: `LibreChat`.
   Supported account types: this organization only.
2. **Redirect URIs (Web):**
   - `https://chat.example-company.com/oauth/openid/callback`
   - `https://chat.example-company.com/api/admin/oauth/openid/callback` (admin panel sign-in)
3. **Certificates & secrets:** create a client secret and put it in `OPENID_CLIENT_SECRET`.
   Note its expiry date in the IT calendar; LibreChat sign-in stops when it expires.
4. Copy the **Application (client) ID** to `OPENID_CLIENT_ID` and set
   `OPENID_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0`.

## 2. Who may sign in: app roles

1. **App roles → Create app role** twice:
   - `LibreChat.User` (allowed member types: users/groups)
   - `LibreChat.Admin` (users/groups)
2. **Enterprise applications → LibreChat → Properties:** set *Assignment required* to **Yes**.
3. **Users and groups:** assign the staff group to `LibreChat.User` and the IT admins to
   `LibreChat.Admin`.

The `.env` settings `OPENID_REQUIRED_ROLE=LibreChat.User` and `OPENID_ADMIN_ROLE=LibreChat.Admin`
(both read from the `roles` claim of the ID token) make LibreChat enforce the same rule.

## 3. API permissions (delegated)

| Permission | Why |
|---|---|
| `openid`, `profile`, `email`, `offline_access` | Sign-in and token refresh |
| `User.Read` | Basic profile |
| `Mail.ReadWrite` | Outlook connector: read own mail and save reply drafts |
| `Calendars.Read` | Outlook connector: read own calendar |
| `Files.Read.All` (Graph) and `AllSites.Read` (SharePoint) | SharePoint file picker |

Grant admin consent. **Do not add `Mail.Send`:** the connector can only save drafts, and
without this permission no token can ever send mail, even by mistake.

## 4. Graph tokens for the Outlook connector

With `OPENID_REUSE_TOKENS=true`, LibreChat keeps the person's Entra ID tokens and exchanges
them (on-behalf-of flow) for a Microsoft Graph token with the scopes in `GRAPH_API_SCOPES`.
That token is sent to the connector as `{{LIBRECHAT_GRAPH_ACCESS_TOKEN}}`, so each person
only reaches their own mailbox.

If the exchange fails with an audience error, add **Expose an API** with an Application ID
URI (`api://<client-id>`) and a scope such as `access_as_user`, and add that scope to
`OPENID_SCOPE`. Confirm the exact requirement in LibreChat's Entra ID guide for the
installed version before go-live.

## 5. Multi-factor sign-in: Conditional Access

**Protection → Conditional Access → New policy** `LibreChat - require MFA`:

- Users: the LibreChat users group (exclude the break-glass accounts)
- Target resources: the `LibreChat` enterprise application
- Grant: require multi-factor authentication (or a phishing-resistant authentication strength)
- Session: sign-in frequency as agreed with IT (for example 12 hours)
- Optional: require a compliant device, or limit to trusted locations

Test it with a sign-in from a new browser before go-live.

## 6. Offboarding

1. Block sign-in and revoke sessions (Entra admin center, or
   `Revoke-MgUserSignInSession -UserId <id>` in Microsoft Graph PowerShell).
2. Remove the `LibreChat.User` assignment.
3. Run `./scripts/offboard_user.sh <email>` (ban) or with `--delete` (remove data).

Because LibreChat reuses Entra ID tokens, an open session ends at the next refresh
(`OPENID_REUSE_MAX_SESSION_AGE_MS`, 15 minutes by default) and no new Graph tokens can be
issued for the connector.
