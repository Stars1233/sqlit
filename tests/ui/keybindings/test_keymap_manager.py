"""Tests for the KeymapManager (additive-merge model)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sqlit.core.keymap import DefaultKeymapProvider, get_keymap, reset_keymap
from sqlit.core.keymap_manager import KeymapManager


class MockSettingsStore:
    """Mock settings store for testing."""

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}

    def load_all(self) -> dict:
        return self.settings

    def save_all(self, settings: dict) -> None:
        self.settings = settings

    def get(self, key: str, default=None):
        return self.settings.get(key, default)


def _write_keymap(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load(tmp_path: Path, name: str, payload: dict) -> KeymapManager:
    file_path = _write_keymap(tmp_path / f"{name}.json", payload)
    manager = KeymapManager(settings_store=MockSettingsStore({"custom_keymap": str(file_path)}))
    manager.initialize()
    return manager


@pytest.fixture(autouse=True)
def reset_keymap_after_test():
    yield
    reset_keymap()


class TestKeymapManagerLifecycle:
    def test_no_custom_keymap_uses_defaults(self):
        manager = KeymapManager(settings_store=MockSettingsStore({}))
        settings = manager.initialize()
        assert settings == {}
        assert manager.get_custom_keymap_name() is None
        assert manager.get_custom_keymap_path() is None

    def test_default_sentinel_skips_loading(self):
        manager = KeymapManager(settings_store=MockSettingsStore({"custom_keymap": "default"}))
        manager.initialize()
        assert manager.get_custom_keymap_name() is None

    def test_invalid_json_is_reported_not_raised(self, tmp_path: Path, capsys):
        path = tmp_path / "invalid.json"
        path.write_text("not valid json", encoding="utf-8")
        manager = KeymapManager(settings_store=MockSettingsStore({"custom_keymap": str(path)}))
        manager.initialize()
        captured = capsys.readouterr()
        assert "Failed to load custom keymap" in captured.err
        assert manager.get_custom_keymap_name() is None

    def test_missing_file_is_reported_not_raised(self, tmp_path: Path, capsys):
        path = tmp_path / "nope.json"
        manager = KeymapManager(settings_store=MockSettingsStore({"custom_keymap": str(path)}))
        manager.initialize()
        captured = capsys.readouterr()
        assert "Failed to load custom keymap" in captured.err
        assert "not found" in captured.err

    def test_reset_to_default(self, tmp_path: Path):
        manager = _load(
            tmp_path,
            "rebind",
            {"keymap": {"leader_commands": [{"key": "Z", "action": "quit"}], "action_keys": []}},
        )
        assert manager.get_custom_keymap_name() is not None
        manager.reset_to_default()
        assert manager.get_custom_keymap_name() is None
        assert manager.get_custom_keymap_path() is None


class TestAdditiveMerge:
    """Overrides should merge over defaults, not replace them."""

    def test_unrelated_defaults_remain(self, tmp_path: Path):
        """An override of one leader command must not erase the others."""
        defaults = DefaultKeymapProvider()
        before = {(c.action, c.menu) for c in defaults.get_leader_commands()}

        _load(
            tmp_path,
            "small",
            {"keymap": {"leader_commands": [{"key": "Z", "action": "quit"}], "action_keys": []}},
        )

        after = {(c.action, c.menu) for c in get_keymap().get_leader_commands()}
        assert before == after, "merge must preserve every default binding's identity"

    def test_leader_override_replaces_matching_default(self, tmp_path: Path):
        _load(
            tmp_path,
            "override",
            {"keymap": {"leader_commands": [{"key": "Z", "action": "quit"}], "action_keys": []}},
        )
        keymap = get_keymap()
        assert keymap.leader("quit", "leader") == "Z"
        # Original "q" no longer maps to quit in the leader menu.
        assert "quit" not in [c.action for c in keymap.get_leader_commands() if c.key == "q" and c.menu == "leader"]

    def test_action_key_override_replaces_matching_default(self, tmp_path: Path):
        _load(
            tmp_path,
            "override-action",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "ctrl+enter", "action": "execute_query", "context": "query_normal"}
                    ],
                }
            },
        )
        keymap = get_keymap()
        assert keymap.action("execute_query") == "ctrl+enter"
        # Original "<enter>" no longer maps to execute_query in query_normal.
        assert not any(
            ak.key == "enter" and ak.action == "execute_query" and ak.context == "query_normal"
            for ak in keymap.get_action_keys()
        )

    def test_missing_label_and_category_inherited_from_default(self, tmp_path: Path):
        """Overrides that match a default should not require label/category."""
        _load(
            tmp_path,
            "inherit",
            {"keymap": {"leader_commands": [{"key": "Z", "action": "quit"}], "action_keys": []}},
        )
        match = next(
            c for c in get_keymap().get_leader_commands()
            if c.action == "quit" and c.menu == "leader"
        )
        assert match.key == "Z"
        assert match.label == "Quit"        # inherited
        assert match.category == "Actions"  # inherited

    def test_new_binding_without_default_requires_label_and_category(self, tmp_path: Path, capsys):
        """A brand-new (action, menu) pair must spell out label and category."""
        _load(
            tmp_path,
            "new-no-meta",
            {
                "keymap": {
                    "leader_commands": [{"key": "X", "action": "some_made_up_action"}],
                    "action_keys": [],
                }
            },
        )
        captured = capsys.readouterr()
        assert "Failed to load custom keymap" in captured.err
        assert '"label" is required' in captured.err

    def test_new_binding_with_full_fields_is_appended(self, tmp_path: Path):
        _load(
            tmp_path,
            "new-full",
            {
                "keymap": {
                    "leader_commands": [
                        {
                            "key": "R",
                            "action": "refresh_tree",
                            "label": "Refresh tree",
                            "category": "View",
                        }
                    ],
                    "action_keys": [],
                }
            },
        )
        commands = get_keymap().get_leader_commands()
        match = [c for c in commands if c.action == "refresh_tree" and c.menu == "leader"]
        assert len(match) == 1 and match[0].key == "R"

    def test_optional_action_key_flags_inherited(self, tmp_path: Path):
        """primary/show/priority should come from the matching default when omitted."""
        # leader_key in "global" context is primary=True, priority=True by default.
        _load(
            tmp_path,
            "inherit-flags",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "comma", "action": "leader_key", "context": "global"}
                    ],
                }
            },
        )
        match = next(
            ak for ak in get_keymap().get_action_keys()
            if ak.action == "leader_key" and ak.context == "global"
        )
        assert match.key == "comma"
        assert match.priority is True  # inherited from default
        assert match.primary is True   # inherited from default


class TestAliasPreservation:
    """Secondary defaults (primary=False) should survive when only the primary slot is overridden."""

    def test_secondary_alias_survives_primary_override(self, tmp_path: Path):
        # refresh_tree in 'tree' has 'f' (primary) and 'R' (alias) by default.
        _load(
            tmp_path,
            "alias",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "F", "action": "refresh_tree", "context": "tree"}
                    ],
                }
            },
        )
        keys = get_keymap().keys_for_action("refresh_tree")
        assert "F" in keys, "user override should be present"
        assert "R" in keys, "secondary alias 'R' must not be dropped"
        assert "f" not in keys, "primary default 'f' should be replaced"


class TestConflictDetection:
    """User-introduced same-key/different-action collisions abort load."""

    def test_user_creates_conflict_with_default(self, tmp_path: Path, capsys):
        # Default: 'i' → enter_insert_mode in query_normal. User binds 'i' to undo.
        _load(
            tmp_path,
            "conflict",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "i", "action": "undo", "context": "query_normal"}
                    ],
                }
            },
        )
        captured = capsys.readouterr()
        assert "Conflicting keybindings detected" in captured.err
        assert "'i'" in captured.err
        assert "query_normal" in captured.err

    def test_user_creates_conflict_with_self(self, tmp_path: Path, capsys):
        # Two user overrides claiming the same key in the same context.
        _load(
            tmp_path,
            "self-conflict",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "ctrl+x", "action": "undo", "context": "query_normal"},
                        {"key": "ctrl+x", "action": "redo", "context": "query_normal"},
                    ],
                }
            },
        )
        captured = capsys.readouterr()
        assert "Conflicting keybindings detected" in captured.err

    def test_default_conflicts_are_tolerated(self, tmp_path: Path, capsys):
        # 'd' in tree maps to both delete_connection and delete_connection_folder
        # by default (resolved by tree-node state at runtime). User does NOT touch
        # those — loading an unrelated override must not flag pre-existing overlaps.
        _load(
            tmp_path,
            "no-touch",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "Z", "action": "undo", "context": "query_normal"}
                    ],
                }
            },
        )
        captured = capsys.readouterr()
        assert "Conflicting" not in captured.err

    def test_leader_conflict(self, tmp_path: Path, capsys):
        # User binds <leader>h to two different actions in the same menu.
        _load(
            tmp_path,
            "leader-conflict",
            {
                "keymap": {
                    "leader_commands": [
                        {"key": "h", "action": "show_help"},
                        {
                            "key": "h",
                            "action": "refresh_tree",
                            "label": "Refresh",
                            "category": "View",
                        },
                    ],
                    "action_keys": [],
                }
            },
        )
        captured = capsys.readouterr()
        assert "leader key 'h'" in captured.err


class TestContextRequired:
    """Omitting context for a context-scoped action is a config trap, not a no-op."""

    def test_missing_context_is_rejected(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "no-context",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "ctrl+enter", "action": "execute_query"}
                    ],
                }
            },
        )
        captured = capsys.readouterr()
        assert "missing \"context\"" in captured.err
        assert "query_normal" in captured.err

    def test_explicit_null_context_is_allowed(self, tmp_path: Path):
        """Setting context to null (when defaults have no null binding) errors only
        if a conflict results — explicit null is the user opting into a global
        binding. Here we use an action that has no default at all, so it's clean."""
        _load(
            tmp_path,
            "null-ctx",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {"key": "ctrl+shift+z", "action": "my_custom_action", "context": None}
                    ],
                }
            },
        )
        match = next(
            ak for ak in get_keymap().get_action_keys()
            if ak.action == "my_custom_action"
        )
        assert match.key == "ctrl+shift+z"
        assert match.context is None


class TestParsing:
    def test_nested_keymap_object(self, tmp_path: Path):
        _load(
            tmp_path,
            "nested",
            {"keymap": {"leader_commands": [{"key": "Q", "action": "quit"}], "action_keys": []}},
        )
        assert get_keymap().leader("quit") == "Q"

    def test_action_key_with_explicit_fields(self, tmp_path: Path):
        # Use a key that doesn't collide with any default in query_normal.
        _load(
            tmp_path,
            "explicit",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [
                        {
                            "key": "ctrl+i",
                            "action": "enter_insert_mode",
                            "context": "query_normal",
                            "primary": False,
                            "show": True,
                            "priority": True,
                        }
                    ],
                }
            },
        )
        match = next(
            ak for ak in get_keymap().get_action_keys()
            if ak.action == "enter_insert_mode" and ak.context == "query_normal"
            and ak.key == "ctrl+i"
        )
        assert match.primary is False
        assert match.show is True
        assert match.priority is True

    def test_missing_action_field_is_rejected(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "no-action",
            {
                "keymap": {
                    "leader_commands": [],
                    "action_keys": [{"key": "i"}],
                }
            },
        )
        captured = capsys.readouterr()
        assert "Failed to load custom keymap" in captured.err
        assert "missing required" in captured.err
