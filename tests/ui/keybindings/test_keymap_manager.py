"""Tests for the state-nested KeymapManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sqlit.core.keymap import get_keymap, reset_keymap
from sqlit.domains.shell.app.keymap_manager import FileBasedKeymapProvider, KeymapManager


class MockSettingsStore:
    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}

    def load_all(self) -> dict:
        return self.settings

    def save_all(self, settings: dict) -> None:
        self.settings = settings

    def get(self, key: str, default=None):
        return self.settings.get(key, default)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load(tmp_path: Path, name: str, payload: dict) -> KeymapManager:
    file_path = _write(tmp_path / f"{name}.json", payload)
    manager = KeymapManager(settings_store=MockSettingsStore({"custom_keymap": str(file_path)}))
    manager.initialize()
    return manager


@pytest.fixture(autouse=True)
def reset_keymap_after_test():
    yield
    reset_keymap()


class TestLifecycle:
    def test_no_custom_keymap_leaves_defaults(self):
        manager = KeymapManager(settings_store=MockSettingsStore({}))
        manager.initialize()
        assert not isinstance(get_keymap(), FileBasedKeymapProvider)

    def test_default_sentinel_skips_loading(self):
        manager = KeymapManager(settings_store=MockSettingsStore({"custom_keymap": "default"}))
        manager.initialize()
        assert not isinstance(get_keymap(), FileBasedKeymapProvider)

    def test_invalid_json_falls_back(self, tmp_path: Path, capsys):
        path = tmp_path / "invalid.json"
        path.write_text("not valid json", encoding="utf-8")
        KeymapManager(settings_store=MockSettingsStore({"custom_keymap": str(path)})).initialize()
        captured = capsys.readouterr()
        assert "Failed to load custom keymap" in captured.err
        assert not isinstance(get_keymap(), FileBasedKeymapProvider)

    def test_missing_file_falls_back(self, tmp_path: Path, capsys):
        KeymapManager(
            settings_store=MockSettingsStore({"custom_keymap": str(tmp_path / "nope.json")})
        ).initialize()
        captured = capsys.readouterr()
        assert "not found" in captured.err


class TestSimpleRemap:
    """Remapping a single key for an existing (state, action) pair."""

    def test_single_key_replaces_default(self, tmp_path: Path):
        _load(
            tmp_path,
            "remap",
            {"keymap": {"action_keys": {"query_normal": {"execute_query": "ctrl+enter"}}}},
        )
        keymap = get_keymap()
        assert keymap.action("execute_query") == "ctrl+enter"
        # Old "enter" no longer triggers execute_query in query_normal.
        assert not any(
            ak.key == "enter" and ak.action == "execute_query" and ak.context == "query_normal"
            for ak in keymap.get_action_keys()
        )

    def test_leader_remap(self, tmp_path: Path):
        _load(
            tmp_path,
            "leader",
            {"keymap": {"leader_commands": {"leader": {"show_help": "question_mark"}}}},
        )
        assert get_keymap().leader("show_help", "leader") == "question_mark"

    def test_unrelated_defaults_remain(self, tmp_path: Path):
        _load(
            tmp_path,
            "small",
            {"keymap": {"leader_commands": {"leader": {"quit": "Z"}}}},
        )
        keymap = get_keymap()
        # toggle_explorer wasn't touched — still on its default 'e'.
        assert keymap.leader("toggle_explorer", "leader") == "e"


class TestAliases:
    """List values let the user keep aliases explicitly."""

    def test_list_creates_primary_plus_aliases(self, tmp_path: Path):
        _load(
            tmp_path,
            "aliases",
            {"keymap": {"action_keys": {"tree": {"refresh_tree": ["F", "ctrl+r"]}}}},
        )
        keys = get_keymap().keys_for_action("refresh_tree")
        assert keys[0] == "F", "first entry is primary"
        assert "ctrl+r" in keys, "alias is preserved"
        # Default 'f' and 'R' both get replaced — user list is authoritative.
        assert "f" not in keys
        assert "R" not in keys

    def test_single_string_replaces_all_default_aliases(self, tmp_path: Path):
        # Default tree_cursor_down has 'j' (primary) and 'down' (alias).
        # Use ctrl+j to avoid colliding with other default tree bindings.
        _load(
            tmp_path,
            "single",
            {"keymap": {"action_keys": {"tree": {"tree_cursor_down": "ctrl+j"}}}},
        )
        keys = get_keymap().keys_for_action("tree_cursor_down")
        assert keys == ["ctrl+j"], "single-string override replaces the entire key set"


class TestStrictness:
    """Unknown (state, action) pairs are rejected with a helpful error."""

    def test_unknown_action_in_state(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "bad",
            {"keymap": {"action_keys": {"tree": {"this_action_does_not_exist": "x"}}}},
        )
        captured = capsys.readouterr()
        assert "Unknown action 'this_action_does_not_exist' in state 'tree'" in captured.err
        assert "Known actions" in captured.err

    def test_unknown_state(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "bad-state",
            {"keymap": {"action_keys": {"made_up_state": {"some_action": "x"}}}},
        )
        captured = capsys.readouterr()
        assert "Unknown action" in captured.err
        assert "made_up_state" in captured.err

    def test_unknown_leader_action(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "bad-leader",
            {"keymap": {"leader_commands": {"leader": {"not_a_leader_action": "x"}}}},
        )
        captured = capsys.readouterr()
        assert "Unknown leader action" in captured.err

    def test_empty_key_string(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "empty",
            {"keymap": {"action_keys": {"tree": {"refresh_tree": ""}}}},
        )
        captured = capsys.readouterr()
        assert "key must be a non-empty string" in captured.err

    def test_empty_key_list(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "empty-list",
            {"keymap": {"action_keys": {"tree": {"refresh_tree": []}}}},
        )
        captured = capsys.readouterr()
        assert "key list must contain at least one key" in captured.err


class TestConflicts:
    """User-introduced collisions abort load with a clear error."""

    def test_user_vs_default_action_key(self, tmp_path: Path, capsys):
        # Default: 'i' → enter_insert_mode in query_normal. User binds 'i' to undo.
        _load(
            tmp_path,
            "conflict",
            {"keymap": {"action_keys": {"query_normal": {"undo": "i"}}}},
        )
        captured = capsys.readouterr()
        assert "Conflicting keybindings detected" in captured.err
        assert "'i'" in captured.err and "query_normal" in captured.err

    def test_user_vs_user_action_key(self, tmp_path: Path, capsys):
        _load(
            tmp_path,
            "self-conflict",
            {
                "keymap": {
                    "action_keys": {
                        "query_normal": {
                            "undo": "ctrl+x",
                            "redo": "ctrl+x",
                        }
                    }
                }
            },
        )
        captured = capsys.readouterr()
        assert "Conflicting keybindings detected" in captured.err

    def test_user_vs_default_leader(self, tmp_path: Path, capsys):
        # Default: <leader>e → toggle_explorer. User binds <leader>e → quit.
        _load(
            tmp_path,
            "leader-conflict",
            {"keymap": {"leader_commands": {"leader": {"quit": "e"}}}},
        )
        captured = capsys.readouterr()
        assert "leader key 'e'" in captured.err

    def test_default_only_overlaps_are_tolerated(self, tmp_path: Path, capsys):
        # 'd' in tree binds two actions in defaults (state-guarded at runtime).
        # An unrelated user override must not trip on that pre-existing overlap.
        _load(
            tmp_path,
            "untouched",
            {"keymap": {"action_keys": {"query_normal": {"undo": "Z"}}}},
        )
        captured = capsys.readouterr()
        assert "Conflicting" not in captured.err


class TestMetadataInheritance:
    """Action metadata (label, category, guard, priority, show) always comes from defaults."""

    def test_leader_inherits_label_and_category(self, tmp_path: Path):
        _load(
            tmp_path,
            "leader-meta",
            {"keymap": {"leader_commands": {"leader": {"show_help": "question_mark"}}}},
        )
        match = next(
            c for c in get_keymap().get_leader_commands()
            if c.action == "show_help" and c.menu == "leader"
        )
        assert match.key == "question_mark"
        assert match.label == "Help"          # inherited
        assert match.category == "Actions"    # inherited

    def test_action_key_inherits_flags(self, tmp_path: Path):
        # leader_key in 'global' is primary=True, priority=True by default.
        _load(
            tmp_path,
            "flags",
            {"keymap": {"action_keys": {"global": {"leader_key": "comma"}}}},
        )
        match = next(
            ak for ak in get_keymap().get_action_keys()
            if ak.action == "leader_key" and ak.context == "global"
        )
        assert match.key == "comma"
        assert match.primary is True
        assert match.priority is True
