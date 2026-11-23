import json

from api.profile_tool_policy import apply_profile_toolset_policy, parse_profile_toolsets


def test_profile_toolset_policy_filters_session_overrides():
    policy = {"shop_a": ["mcp-store_crm"]}

    # A persisted session override cannot re-enable a built-in or another MCP.
    assert apply_profile_toolset_policy(
        "shop_a",
        ["mcp-store_crm", "terminal", "mcp-other"],
        policy=policy,
    ) == ["mcp-store_crm"]


def test_profile_toolset_policy_denies_unknown_and_invalid_profiles():
    policy = json.dumps({"shop_a": ["mcp-store_crm"], "shop_b": "not-a-list"})

    assert apply_profile_toolset_policy("shop_b", ["terminal"], policy=policy) == []
    assert apply_profile_toolset_policy("unmapped", ["terminal"], policy=policy) == []
    assert apply_profile_toolset_policy("shop_a", ["terminal"], policy="not-json") == []


def test_profile_toolset_policy_is_opt_in_for_non_shared_installs():
    assert apply_profile_toolset_policy("default", ["terminal"], policy=None) == ["terminal"]
    assert parse_profile_toolsets(None) is None
