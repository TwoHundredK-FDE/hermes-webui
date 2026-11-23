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

This is a profile ownership boundary with a chat tool allowlist, not full role-
based access control or an OS-level sandbox. It does not define billing,
support, or platform-operator roles. A profile-specific CRM key must still
enforce tenant and feature scopes in the Worker. IdP policy owns MFA. Keep
tenant profile workspaces and MCP configuration separate, and do not add
host-level tools to a tenant allowlist. A future tenant-admin console must add
explicit role claims and route authorization before exposing billing or
platform-operator capabilities to store owners.

Regression coverage lives in `tests/test_trusted_header_auth.py`.
