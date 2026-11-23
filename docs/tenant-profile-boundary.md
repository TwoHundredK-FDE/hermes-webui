# Tenant profile boundary for SSO sessions

Hermes profiles are the tenant boundary for the shared-WebUI deployment model.
When an authenticated SSO session carries a `bound_profile`, every request is
forced into that profile and profile discovery and administration stay within
that boundary.

## Route behavior

- `GET /api/profiles` returns only the profile matching the session binding and
  advertises `single_profile_mode: true`. The UI uses that flag to hide profile
  switching and creation controls; the API remains authoritative.
- `POST /api/profile/switch` may select only the bound profile.
- `POST /api/profile/create` and `POST /api/profile/delete` are forbidden for
  profile-bound sessions.
- `POST /api/session/new` may omit `profile` or name the bound profile, but it
  rejects a different profile before workspace resolution, worktree creation,
  or session persistence. Dedicated isolated-profile deployments enforce the
  same rule against their configured profile.
- If the server cannot resolve the session binding, profile enumeration fails
  closed and profile mutations are denied. A verified session with no binding
  retains the server's existing global profile-management behavior.
- Profile-bound OIDC must declare a server-owned `profile_toolsets` map for
  every profile target in `profile_map`. The chat runner intersects the
  configured toolsets with that allowlist **after** applying any saved
  per-session toolset override, so an older session cannot restore a tool the
  tenant is not allowed to use. A missing, malformed, or unmapped entry gives
  that profile no tools. Example: `{"shop_a":["mcp-store_crm"]}`.
- Profile-bound sessions cannot use the embedded PTY terminal. Authentication
  does not grant a tenant arbitrary commands as the shared Hermes service user.
  Configure a separate operator profile for host administration.
- Profile-bound OIDC requires server-owned `role_claim`/`role_map` and
  `mfa_claim`/`mfa_values` in addition to profile binding. A login must resolve
  to exactly one `owner` or `viewer` role and contain an exact configured MFA
  assertion from the IdP. Missing assertions are rejected at login; existing
  sessions without the recorded assertion fail closed. Viewers may use safe
  read methods only; every write method and chat/tool command is rejected at
  the central request authorization boundary. Owners retain the profile's
  configured capabilities.

Example for an IdP that emits group names in a `groups` array:

```yaml
webui_oidc:
  profile_claim: groups
  profile_map:
    shop-a-owner: shop_a
    shop-a-viewer: shop_a
  role_claim: groups
  role_map:
    shop-a-owner: owner
    shop-a-viewer: viewer
  mfa_claim: amr
  mfa_values: [otp, mfa]
```

Keep these maps in server-owned configuration. Replace the example MFA values
with the identity provider's documented assertion values. Do not let a tenant
profile change the mapping that grants its own login role or MFA status.

For Google OIDC, use `mfa_claim: amr` and `mfa_values: [mfa]`. The WebUI
requests the claim as essential in the ID token, but this request alone does
not enable it. Google's current setup requires the OAuth app to be published
and verified, then **Authentication strength claims** to be enabled under the
Google Auth Platform Security Bundle. The account or Workspace policy must
also require MFA. Google may still omit `amr` when it cannot attest to the
authentication method; the WebUI must reject that login. Before rollout, sign
in with the actual owner account and confirm the returned, validated ID token
contains `amr: ["mfa", ...]`. If Google's verification or claim setup cannot be
completed, use an IdP that can reliably assert MFA rather than weakening the
WebUI's fail-closed check. See Google's [OpenID Connect claim reference](https://developers.google.com/identity/openid-connect/openid-connect#an-id-tokens-payload)
and [Security Bundle setup and MFA claim behavior](https://developers.google.com/identity/siwg/security-bundle).

This provides an owner/viewer role boundary with a chat tool allowlist, not a
general-purpose role system or an OS-level sandbox. It does not define separate
billing, support, or platform-operator roles. A profile-specific CRM key must still
enforce tenant and feature scopes in the Worker. IdP policy owns MFA. Keep
tenant profile workspaces and MCP configuration separate, and do not add
host-level tools to a tenant allowlist. A future tenant-admin console must add
explicit role claims and route authorization before exposing billing or
platform-operator capabilities to store owners.

Regression coverage lives in `tests/test_trusted_header_auth.py`.
