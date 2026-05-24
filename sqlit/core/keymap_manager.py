"""Keymap management utilities for sqlit.

User keymaps merge additively over the default keymap: each override
replaces the matching default's primary binding (by ``(action, menu)`` for
leader commands and ``(action, context)`` for action keys). Secondary
aliases — defaults marked ``primary=False`` with the same identity — are
preserved unless the user overrides them explicitly. New entries are
appended. Optional fields are filled in from the matching default when
omitted, so overrides can be as small as ``{"key": "X", "action": "..."}``.

After merging, the keymap is validated for conflicts (two different actions
bound to the same key in the same context/menu); conflicts abort load with
a clear error so the user can fix their config.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlit.shared.core.protocols import SettingsStoreProtocol
from sqlit.shared.core.store import CONFIG_DIR

from .keymap import (
    ActionKeyDef,
    DefaultKeymapProvider,
    KeymapProvider,
    LeaderCommandDef,
    set_keymap,
)

CUSTOM_KEYMAP_SETTINGS_KEY = "custom_keymap"
CUSTOM_KEYMAP_DIR = CONFIG_DIR / "keymaps"


def build_textual_keymap(provider: KeymapProvider) -> dict[str, str]:
    """Build a Textual-compatible keymap dict from a KeymapProvider.

    Groups action keys by action name (across contexts) and joins the keys
    with commas — Textual's set_keymap accepts comma-separated key lists.
    Use the result with ``App.set_keymap(...)`` so that Bindings with
    matching ``id=`` get their keys overridden at runtime.
    """
    by_action: dict[str, list[str]] = defaultdict(list)
    for ak in provider.get_action_keys():
        if ak.key not in by_action[ak.action]:
            by_action[ak.action].append(ak.key)
    return {action: ",".join(keys) for action, keys in by_action.items()}


class FileBasedKeymapProvider(KeymapProvider):
    """Keymap provider built by merging user overrides onto the defaults."""

    def __init__(
        self,
        name: str,
        leader_commands: list[LeaderCommandDef],
        action_keys: list[ActionKeyDef],
    ):
        self._name = name
        self._leader_commands = leader_commands
        self._action_keys = action_keys

    @property
    def name(self) -> str:
        return self._name

    def get_leader_commands(self) -> list[LeaderCommandDef]:
        return list(self._leader_commands)

    def get_action_keys(self) -> list[ActionKeyDef]:
        return list(self._action_keys)


class KeymapManager:
    """Centralized keymap handling for the app."""

    def __init__(
        self,
        settings_store: SettingsStoreProtocol | None = None,
    ) -> None:
        from sqlit.domains.shell.store.settings import SettingsStore

        self._settings_store = settings_store or SettingsStore.get_instance()
        self._custom_keymap_name: str | None = None
        self._custom_keymap_path: Path | None = None

    def initialize(self) -> dict:
        settings = self._settings_store.load_all()
        self.load_custom_keymap(settings)
        return settings

    def load_custom_keymap(self, settings: dict) -> None:
        keymap_name = settings.get(CUSTOM_KEYMAP_SETTINGS_KEY)
        if not keymap_name or not isinstance(keymap_name, str):
            return
        if keymap_name.strip() in ("", "default"):
            return

        try:
            path = self._resolve_keymap_path(keymap_name.strip())
            self._register_custom_keymap(path, keymap_name.strip())
        except Exception as exc:
            print(
                f"[sqlit] Failed to load custom keymap '{keymap_name}': {exc}",
                file=sys.stderr,
            )

    def _resolve_keymap_path(self, keymap_name: str) -> Path:
        if keymap_name.startswith(("~", "/")) or Path(keymap_name).is_absolute():
            return Path(keymap_name).expanduser()

        name = Path(keymap_name).stem
        return CUSTOM_KEYMAP_DIR / f"{name}.json"

    def _register_custom_keymap(self, path: Path, keymap_name: str) -> None:
        path = path.expanduser()
        if not path.exists():
            raise ValueError(f"Keymap file not found: {path}")

        keymap = self._load_keymap_from_file(path, keymap_name)
        set_keymap(keymap)
        self._custom_keymap_name = keymap_name
        self._custom_keymap_path = path.resolve()

    def _load_keymap_from_file(self, path: Path, keymap_name: str) -> FileBasedKeymapProvider:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Failed to read keymap JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Keymap file must contain a JSON object.")

        keymap_data = payload.get("keymap", payload)
        if not isinstance(keymap_data, dict):
            raise ValueError('Keymap file "keymap" must be a JSON object.')

        user_leader_data = keymap_data.get("leader_commands", [])
        user_action_data = keymap_data.get("action_keys", [])

        if not isinstance(user_leader_data, list):
            raise ValueError('"leader_commands" must be a list.')
        if not isinstance(user_action_data, list):
            raise ValueError('"action_keys" must be a list.')

        defaults = DefaultKeymapProvider()
        base_leader = defaults.get_leader_commands()
        base_action = defaults.get_action_keys()

        # For inheritance lookup: prefer the primary default when multiple
        # defaults share an (action, identity).
        leader_by_identity: dict[tuple[str, str], LeaderCommandDef] = {
            (cmd.action, cmd.menu): cmd for cmd in base_leader
        }
        action_by_identity: dict[tuple[str, str | None], ActionKeyDef] = {}
        for ak in base_action:
            existing = action_by_identity.get((ak.action, ak.context))
            if existing is None or (ak.primary and not existing.primary):
                action_by_identity[(ak.action, ak.context)] = ak

        # All known contexts per action (across defaults) — used to reject
        # overrides that omit context when the action is context-scoped.
        contexts_by_action: dict[str, set[str | None]] = defaultdict(set)
        for ak in base_action:
            contexts_by_action[ak.action].add(ak.context)

        user_leader = self._parse_leader_commands(user_leader_data, leader_by_identity)
        user_action = self._parse_action_keys(
            user_action_data, action_by_identity, contexts_by_action
        )

        merged_leader = self._merge_leader_commands(base_leader, user_leader)
        merged_action = self._merge_action_keys(base_action, user_action)

        self._detect_conflicts(merged_leader, merged_action, user_leader, user_action)

        return FileBasedKeymapProvider(keymap_name, merged_leader, merged_action)

    def _parse_leader_commands(
        self,
        data: list[Any],
        defaults_by_identity: dict[tuple[str, str], LeaderCommandDef],
    ) -> list[LeaderCommandDef]:
        commands: list[LeaderCommandDef] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f'Leader command at index {i} must be an object.')

            key = item.get("key")
            action = item.get("action")
            if not isinstance(key, str) or not key:
                raise ValueError(f'Leader command at index {i} missing required "key".')
            if not isinstance(action, str) or not action:
                raise ValueError(f'Leader command at index {i} missing required "action".')

            menu_raw = item.get("menu")
            if menu_raw is None:
                menu = "leader"
            elif isinstance(menu_raw, str) and menu_raw:
                menu = menu_raw
            else:
                raise ValueError(f'Leader command at index {i} "menu" must be a non-empty string.')

            default = defaults_by_identity.get((action, menu))

            label = item.get("label")
            if label is None and default is not None:
                label = default.label
            if not isinstance(label, str) or not label:
                raise ValueError(
                    f'Leader command at index {i} ({action!r} in menu {menu!r}) '
                    f'has no matching default — "label" is required for new bindings.'
                )

            category = item.get("category")
            if category is None and default is not None:
                category = default.category
            if not isinstance(category, str) or not category:
                raise ValueError(
                    f'Leader command at index {i} ({action!r} in menu {menu!r}) '
                    f'has no matching default — "category" is required for new bindings.'
                )

            if "guard" in item:
                guard = item.get("guard")
                if guard is not None and not isinstance(guard, str):
                    raise ValueError(f'Leader command at index {i} "guard" must be a string or null.')
            else:
                guard = default.guard if default is not None else None

            commands.append(
                LeaderCommandDef(
                    key=key,
                    action=action,
                    label=label,
                    category=category,
                    guard=guard,
                    menu=menu,
                )
            )

        return commands

    def _parse_action_keys(
        self,
        data: list[Any],
        defaults_by_identity: dict[tuple[str, str | None], ActionKeyDef],
        contexts_by_action: dict[str, set[str | None]],
    ) -> list[ActionKeyDef]:
        action_keys: list[ActionKeyDef] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f'Action key at index {i} must be an object.')

            key = item.get("key")
            action = item.get("action")
            if not isinstance(key, str) or not key:
                raise ValueError(f'Action key at index {i} missing required "key".')
            if not isinstance(action, str) or not action:
                raise ValueError(f'Action key at index {i} missing required "action".')

            context_provided = "context" in item
            context = item.get("context")
            if context is not None and not isinstance(context, str):
                raise ValueError(f'Action key at index {i} "context" must be a string or null.')

            # Reject the silent-no-op trap: user writes a context-scoped action
            # without specifying context, which would create a brand-new
            # context=None binding while the default stays in place.
            known_contexts = contexts_by_action.get(action)
            if not context_provided and known_contexts and known_contexts != {None}:
                contexts_sorted = sorted(c for c in known_contexts if c is not None)
                raise ValueError(
                    f'Action key at index {i} for action {action!r} is missing "context". '
                    f'This action is bound in default context(s): {contexts_sorted}. '
                    f'Specify "context" to override one of them, or set it explicitly to null '
                    f'to add a global (no-context) binding.'
                )

            default = defaults_by_identity.get((action, context))

            if "guard" in item:
                guard = item.get("guard")
                if guard is not None and not isinstance(guard, str):
                    raise ValueError(f'Action key at index {i} "guard" must be a string or null.')
            else:
                guard = default.guard if default is not None else None

            primary = item.get("primary")
            if primary is None:
                primary = default.primary if default is not None else True
            if not isinstance(primary, bool):
                raise ValueError(f'Action key at index {i} "primary" must be a boolean.')

            show = item.get("show")
            if show is None:
                show = default.show if default is not None else False
            if not isinstance(show, bool):
                raise ValueError(f'Action key at index {i} "show" must be a boolean.')

            priority = item.get("priority")
            if priority is None:
                priority = default.priority if default is not None else False
            if not isinstance(priority, bool):
                raise ValueError(f'Action key at index {i} "priority" must be a boolean.')

            action_keys.append(
                ActionKeyDef(
                    key=key,
                    action=action,
                    context=context,
                    guard=guard,
                    primary=primary,
                    show=show,
                    priority=priority,
                )
            )

        return action_keys

    @staticmethod
    def _merge_leader_commands(
        base: list[LeaderCommandDef], user: list[LeaderCommandDef]
    ) -> list[LeaderCommandDef]:
        # Leader defaults are unique by (action, menu); drop the matching
        # default entirely when the user overrides it.
        overridden = {(u.action, u.menu) for u in user}
        kept = [cmd for cmd in base if (cmd.action, cmd.menu) not in overridden]
        return kept + user

    @staticmethod
    def _merge_action_keys(
        base: list[ActionKeyDef], user: list[ActionKeyDef]
    ) -> list[ActionKeyDef]:
        # An action_key override claims the *primary* slot for (action, context).
        # Defaults with the same identity that are marked primary=False
        # (e.g. arrow-key aliases for j/k movement) survive as aliases.
        overridden = {(u.action, u.context) for u in user}
        kept = [
            ak for ak in base
            if (ak.action, ak.context) not in overridden or not ak.primary
        ]
        return kept + user

    @staticmethod
    def _detect_conflicts(
        merged_leader: list[LeaderCommandDef],
        merged_action: list[ActionKeyDef],
        user_leader: list[LeaderCommandDef],
        user_action: list[ActionKeyDef],
    ) -> None:
        """Raise ValueError on user-introduced bindings that collide.

        Defaults intentionally bind some keys to multiple actions in the
        same context (e.g. ``d`` in ``tree`` for both delete_connection
        and delete_connection_folder, disambiguated by tree-node state at
        runtime). We don't flag those. We *do* flag any conflict that a
        user override either created or contributed to — those almost
        always indicate a typo or misunderstanding.
        """
        conflicts: list[str] = []

        user_leader_slots = {(u.key, u.menu) for u in user_leader}
        leader_by_slot: dict[tuple[str, str], set[str]] = defaultdict(set)
        for cmd in merged_leader:
            leader_by_slot[(cmd.key, cmd.menu)].add(cmd.action)
        for (key, menu), actions in sorted(leader_by_slot.items()):
            if len(actions) > 1 and (key, menu) in user_leader_slots:
                conflicts.append(
                    f"leader key {key!r} in menu {menu!r} is bound to multiple actions: "
                    f"{sorted(actions)}"
                )

        user_action_slots = {(u.key, u.context) for u in user_action}
        action_by_slot: dict[tuple[str, str | None], set[str]] = defaultdict(set)
        for ak in merged_action:
            action_by_slot[(ak.key, ak.context)].add(ak.action)
        for (key, ctx), actions in sorted(
            action_by_slot.items(), key=lambda t: (t[0][0], t[0][1] or "")
        ):
            if len(actions) > 1 and (key, ctx) in user_action_slots:
                conflicts.append(
                    f"key {key!r} in context {ctx!r} is bound to multiple actions: "
                    f"{sorted(actions)}"
                )

        if conflicts:
            lines = "\n  - ".join(conflicts)
            raise ValueError(
                f"Conflicting keybindings detected ({len(conflicts)}):\n  - {lines}\n"
                f"Resolve by removing or rebinding the conflicting entries in your keymap."
            )

    def get_custom_keymap_name(self) -> str | None:
        return self._custom_keymap_name

    def get_custom_keymap_path(self) -> Path | None:
        return self._custom_keymap_path

    def reset_to_default(self) -> None:
        from .keymap import reset_keymap

        reset_keymap()
        self._custom_keymap_name = None
        self._custom_keymap_path = None
