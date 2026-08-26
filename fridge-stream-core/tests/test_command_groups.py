"""Tests for command group enablement and binding."""

from core.command_groups import CommandGroups, DEFAULT_GROUPS, resolve_active_groups


def test_core_always_on():
    cg = CommandGroups({"command_groups": {"core": {"enabled": False, "always": True}}})
    assert cg.is_enabled("core") is True


def test_minecraft_bind_respects_config():
    cfg = {
        "minecraft": {"enabled": False},
        "command_groups": {
            "minecraft": {"enabled": True, "bind": "minecraft"},
        },
    }
    cg = CommandGroups(cfg)
    assert cg.is_enabled("minecraft") is False

    cfg["minecraft"]["enabled"] = True
    cg.reload(cfg)
    assert cg.is_enabled("minecraft") is True


def test_points_bind():
    cfg = {
        "points": {"enabled": False},
        "command_groups": {"points": {"enabled": True, "bind": "points"}},
    }
    cg = CommandGroups(cfg)
    assert cg.is_enabled("points") is False


def test_integration_running_override():
    cfg = {
        "minecraft": {"enabled": True},
        "command_groups": {"minecraft": {"enabled": True, "bind": "minecraft"}},
    }
    cg = CommandGroups(cfg)
    assert cg.is_enabled("minecraft", integration_running={"minecraft": False}) is False
    assert cg.is_enabled("minecraft", integration_running={"minecraft": True}) is True


def test_list_groups_includes_defaults():
    cg = CommandGroups({})
    ids = {g["id"] for g in cg.list_groups()}
    assert "core" in ids
    assert "minecraft" in ids
    assert DEFAULT_GROUPS


def test_resolve_active_groups_games_keys():
    cfg = {
        "minecraft": {"enabled": True},
        "points": {"enabled": True},
    }
    groups = resolve_active_groups(cfg, ["minecraft"], {"points": True})
    assert groups["core"] is True
    assert "core" in groups
    assert groups["minecraft"] is True
    assert set(groups.enabled()) >= {"core", "minecraft", "points"}
