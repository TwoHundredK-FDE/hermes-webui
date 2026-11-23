"""Fail-closed toolset limits for profile-bound shared WebUI sessions."""

from __future__ import annotations

import json
import os
from typing import Any


PROFILE_TOOLSETS_ENV = "HERMES_WEBUI_OIDC_PROFILE_TOOLSETS"


def parse_profile_toolsets(raw: Any) -> dict[str, frozenset[str]] | None:
    """Parse the profile -> allowed toolsets map.

    ``None`` means no policy was configured. Invalid top-level input becomes an
    empty map, which denies all toolsets when enforced. Invalid individual
    entries also become empty sets rather than broadening access.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}

    parsed: dict[str, frozenset[str]] = {}
    for profile, toolsets in raw.items():
        if not isinstance(profile, str) or not profile.strip():
            continue
        if not isinstance(toolsets, list) or any(
            not isinstance(item, str) or not item.strip() for item in toolsets
        ):
            parsed[profile.strip()] = frozenset()
            continue
        parsed[profile.strip()] = frozenset(item.strip() for item in toolsets)
    return parsed


def apply_profile_toolset_policy(
    profile: str | None,
    toolsets: list[str] | tuple[str, ...],
    *,
    policy: Any = None,
) -> list[str]:
    """Intersect requested toolsets with the profile's configured allowlist.

    A configured policy denies unknown profiles and malformed entries. With no
    policy at all, preserve Hermes' existing behavior for non-shared installs.
    """
    if policy is None:
        policy = os.environ.get(PROFILE_TOOLSETS_ENV)
    mapping = parse_profile_toolsets(policy)
    requested = list(toolsets or [])
    if mapping is None:
        return requested
    allowed = mapping.get(str(profile or "default"), frozenset())
    return [name for name in requested if name in allowed]

