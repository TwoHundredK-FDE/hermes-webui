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

This is profile ownership isolation, not full role-based access control. It
does not define billing, support, or platform-operator roles. IdP policy owns
MFA, and a future tenant-admin console must add explicit role claims and route
authorization before exposing those capabilities to store owners.

Regression coverage lives in `tests/test_trusted_header_auth.py`.
