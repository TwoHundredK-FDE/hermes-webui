from types import SimpleNamespace
from urllib.parse import urlparse


def test_profiles_route_returns_active_profile(monkeypatch):
    import api.profiles as profiles
    import api.routes as routes

    expected_profiles = [{"name": "default", "is_default": True}]

    monkeypatch.setattr(profiles, "list_profiles_api", lambda: expected_profiles)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    monkeypatch.setattr(routes, "_is_isolated_profile_mode", lambda: False)
    # This unit test covers the legacy, unbound profile-listing response. The
    # profile-bound SSO guard separately fails closed when authentication context
    # cannot be resolved; don't make this response-shape test depend on a fake
    # handler implementing auth cookies and headers.
    monkeypatch.setattr(routes, "_profile_bound_session", lambda _handler: None)
    monkeypatch.setattr(
        routes,
        "j",
        lambda _handler, payload, status=200: {"status": status, "payload": payload},
    )

    response = routes.handle_get(SimpleNamespace(), urlparse("/api/profiles"))

    assert response == {
        "status": 200,
        "payload": {
            "profiles": expected_profiles,
            "active": "default",
            "single_profile_mode": False,
        },
    }
