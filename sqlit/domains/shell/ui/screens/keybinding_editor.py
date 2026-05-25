"""In-app keybinding editor.

Lists every binding from the active keymap (defaults + user overrides),
lets the user rebind one by pressing a new key, revert one to default,
or reset every override. Writes flow through
:class:`sqlit.domains.shell.app.keymap_manager.KeymapManager` so the change
is persisted to ``~/.config/sqlit/keymap.json`` and applied to the running
app live — no restart needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sqlit.core.keymap import (
    ActionKeyDef,
    DefaultKeymapProvider,
    LeaderCommandDef,
    format_key,
    get_keymap,
)
from sqlit.shared.ui.widgets import Dialog, FilterInput

from .key_capture import KeyCaptureScreen


class _NarrowConfirmScreen(ModalScreen[bool | None]):
    """Small yes/no confirm modal used by the keybinding editor.

    The shared :class:`ConfirmScreen` stretches its dialog to ~80% of the
    viewport because its inner OptionList has no width cap. Subclassing it
    and overriding DEFAULT_CSS dropped the centering/transparent-background
    styles, so this screen redeclares the layout from scratch — same
    behaviour, tighter footprint.
    """

    BINDINGS = [
        Binding("y", "yes", "Yes", show=False),
        Binding("n", "no", "No", show=False),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("enter", "select_option", "Select", show=False),
    ]

    CSS = """
    _NarrowConfirmScreen {
        align: center middle;
        background: transparent;
    }

    #narrow-confirm-dialog {
        width: 44;
        max-width: 44;
    }

    #narrow-confirm-description {
        margin-bottom: 1;
        color: $text-muted;
        height: auto;
    }

    #narrow-confirm-list {
        height: auto;
        border: none;
        width: 100%;
    }

    #narrow-confirm-list > .option-list--option {
        padding: 0;
    }
    """

    def __init__(self, title: str, description: str | None = None) -> None:
        super().__init__()
        self._title = title
        self._description = description

    def compose(self) -> ComposeResult:
        shortcuts: list[tuple[str, str]] = [("Yes", "y"), ("No", "n")]
        with Dialog(id="narrow-confirm-dialog", title=self._title, shortcuts=shortcuts):
            if self._description:
                yield Static(
                    self._description, id="narrow-confirm-description", markup=True
                )
            yield OptionList(
                Option("Yes", id="yes"),
                Option("No", id="no"),
                id="narrow-confirm-list",
            )

    def on_mount(self) -> None:
        self.query_one("#narrow-confirm-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "yes":
            self.dismiss(True)
        elif event.option.id == "no":
            self.dismiss(False)

    def action_select_option(self) -> None:
        ol = self.query_one("#narrow-confirm-list", OptionList)
        if ol.highlighted is None:
            return
        option = ol.get_option_at_index(ol.highlighted)
        if option.id == "yes":
            self.dismiss(True)
        elif option.id == "no":
            self.dismiss(False)

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # Don't leak actions to underlying screens while a deeper modal is open.
        if self.app.screen is not self:
            return False
        return super().check_action(action, parameters)

if TYPE_CHECKING:
    from sqlit.domains.shell.app.main import SSMSTUI


# Friendly leader-menu names — the raw IDs ("ry", "rye", "gc") are
# implementation detail, so spell them out for the editor's section
# headers. Anything not in here falls back to the menu ID.
_LEADER_MENU_LABELS: dict[str, str] = {
    "leader": "Leader (space)",
    "delete": "Delete operator (d)",
    "yank": "Yank operator (y)",
    "change": "Change operator (c)",
    "g": "g motion",
    "gc": "gc comment operator",
    "ry": "Results yank (y)",
    "rye": "Results export (ye)",
    "rg": "Results g motion",
    "vy": "Value-view yank (y)",
}

# Friendly state names for action_keys section headers — same idea.
_STATE_LABELS: dict[str, str] = {
    "global": "Global",
    "navigation": "Pane navigation",
    "tree": "Explorer tree",
    "tree_visual": "Explorer tree (visual)",
    "tree_filter": "Explorer tree filter",
    "query_normal": "Query editor (normal)",
    "query_insert": "Query editor (insert)",
    "query_visual": "Query editor (visual)",
    "query_visual_line": "Query editor (visual line)",
    "autocomplete": "Query editor (autocomplete)",
    "results": "Results table",
    "results_filter": "Results filter",
    "value_view": "Value view",
    "error_dialog": "Error dialog",
    "connection_editor": "Connection editor",
}


@dataclass
class _Row:
    """One editable binding row in the list."""

    kind: str  # "action" or "leader"
    scope: str  # state name for action; menu name for leader
    action: str
    label: str  # display name for the action
    current_keys: list[str]  # primary first, then aliases (action) — leader has just one
    default_keys: list[str]  # what defaults would give

    @property
    def primary_key(self) -> str:
        return self.current_keys[0] if self.current_keys else ""

    @property
    def is_customized(self) -> bool:
        return self.current_keys != self.default_keys

    @property
    def identity(self) -> tuple[str, str, str]:
        """Stable identity for highlight-restoration across rebuilds."""
        return (self.kind, self.scope, self.action)


class KeybindingEditorScreen(ModalScreen):
    """Modal for editing keybindings in-app.

    Navigation: ``j``/``k`` or arrows. ``enter`` or ``r`` to rebind the
    highlighted row, ``R`` to revert it to default (with confirmation),
    ``shift+D`` to reset every override (with confirmation), ``/`` to
    filter, ``esc`` to close.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Close", priority=True),
        Binding("enter", "rebind", "Rebind", show=False),
        Binding("r", "revert", "Revert one", show=False),
        Binding("R", "reset_all", "Reset all", show=False),
        Binding("slash", "open_filter", "Filter", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    CSS = """
    KeybindingEditorScreen {
        align: center middle;
        background: transparent;
    }

    #kb-dialog {
        width: 90;
        max-width: 95%;
        height: 80%;
        max-height: 90%;
    }

    #kb-filter {
        background: $surface;
    }

    #kb-scroll {
        height: 1fr;
        background: $surface;
        border: none;
    }

    #kb-list {
        height: auto;
        background: $surface;
        border: none;
        padding: 0;
    }

    #kb-list > .option-list--option {
        padding: 0 1;
    }

    #kb-empty {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Filter state mirrors the QueryHistory pattern: a `/` toggle plus
        # printable-character buffer driven by on_key, not a focused Input.
        self._filter_active: bool = False
        self._filter_text: str = ""
        self._rows: list[_Row] = []
        self._visible_rows: list[_Row] = []
        self._last_highlight_identity: tuple[str, str, str] | None = None

    # ----------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        shortcuts = [
            ("Rebind", "<enter>"),
            ("Revert", "r"),
            ("Reset all", "R"),
        ]
        with Dialog(id="kb-dialog", title="Edit Keybindings", shortcuts=shortcuts):
            yield FilterInput(id="kb-filter")
            with VerticalScroll(id="kb-scroll"):
                yield OptionList(id="kb-list")

    def on_mount(self) -> None:
        try:
            self.query_one("#kb-filter", FilterInput).hide()
        except Exception:
            pass
        self._rebuild_rows()
        self._render_list()
        try:
            option_list = self.query_one("#kb-list", OptionList)
            option_list.focus()
            self._move_highlight_to_first_row(option_list)
        except Exception:
            pass

    # ------------------------------------------------------- data loading

    def _rebuild_rows(self) -> None:
        """Build the row list from the current keymap + defaults."""
        current = get_keymap()
        defaults = DefaultKeymapProvider()

        # Group action keys by (action, context) so we can list primary+aliases
        # together. The keymap provider returns primary entries first because
        # of how DefaultKeymapProvider builds the list; we preserve that.
        action_index = self._group_action_keys(current.get_action_keys())
        default_action_index = self._group_action_keys(defaults.get_action_keys())

        leader_index = self._group_leader(current.get_leader_commands())
        default_leader_index = self._group_leader(defaults.get_leader_commands())

        rows: list[_Row] = []

        # Leader commands first — these are the most discoverable / most
        # likely to be customized, so they go on top.
        for (menu, action), cmds in leader_index.items():
            default_cmds = default_leader_index.get((menu, action), [])
            current_keys = [c.key for c in cmds]
            default_keys = [c.key for c in default_cmds]
            # Use the default command's label as the display text — that's
            # the human-readable name that lives in the keymap defs.
            template = default_cmds[0] if default_cmds else cmds[0]
            rows.append(
                _Row(
                    kind="leader",
                    scope=menu,
                    action=action,
                    label=template.label,
                    current_keys=current_keys,
                    default_keys=default_keys,
                )
            )

        # Then action keys, grouped by state. One row per (action, state).
        for (state, action), aks in action_index.items():
            default_aks = default_action_index.get((state, action), [])
            current_keys = [ak.key for ak in aks]
            default_keys = [ak.key for ak in default_aks]
            rows.append(
                _Row(
                    kind="action",
                    scope=state or "global",
                    action=action,
                    label=action,
                    current_keys=current_keys,
                    default_keys=default_keys,
                )
            )

        self._rows = rows

    @staticmethod
    def _group_action_keys(
        keys: list[ActionKeyDef],
    ) -> dict[tuple[str | None, str], list[ActionKeyDef]]:
        out: dict[tuple[str | None, str], list[ActionKeyDef]] = {}
        for ak in keys:
            key_id = (ak.context, ak.action)
            out.setdefault(key_id, []).append(ak)
        # Sort: primary first within each (state, action). Stable so the
        # rest of the order follows declaration order.
        for v in out.values():
            v.sort(key=lambda ak: (0 if ak.primary else 1))
        return out

    @staticmethod
    def _group_leader(
        commands: list[LeaderCommandDef],
    ) -> dict[tuple[str, str], list[LeaderCommandDef]]:
        out: dict[tuple[str, str], list[LeaderCommandDef]] = {}
        for cmd in commands:
            out.setdefault((cmd.menu, cmd.action), []).append(cmd)
        return out

    # --------------------------------------------------------- rendering

    def _matches_filter(self, row: _Row) -> bool:
        if not self._filter_text:
            return True
        needle = self._filter_text.lower()
        haystack_parts = [
            row.action.lower(),
            row.label.lower(),
            row.scope.lower(),
            row.primary_key.lower(),
            _LEADER_MENU_LABELS.get(row.scope, row.scope).lower()
            if row.kind == "leader"
            else _STATE_LABELS.get(row.scope, row.scope).lower(),
        ]
        return any(needle in part for part in haystack_parts)

    def _render_list(self) -> None:
        try:
            option_list = self.query_one("#kb-list", OptionList)
        except Exception:
            return

        # Filter, then group rows by scope. Within each scope we keep the
        # row's natural order (which preserves the declaration order from
        # _build_action_keys / _build_leader_commands).
        leader_rows: dict[str, list[_Row]] = {}
        action_rows: dict[str, list[_Row]] = {}
        for row in self._rows:
            if not self._matches_filter(row):
                continue
            bucket = leader_rows if row.kind == "leader" else action_rows
            bucket.setdefault(row.scope, []).append(row)

        options: list[Option] = []
        visible: list[_Row] = []

        # Leader sections in a deliberate order — the main "leader" menu
        # first since that's the only one users typically encounter as a
        # menu, then the vim-style operators in a sensible reading order.
        leader_order = ["leader", "delete", "yank", "change", "g", "gc", "ry", "rye", "rg", "vy"]
        leader_keys_seen: set[str] = set()
        for menu in leader_order + sorted(leader_rows.keys()):
            if menu in leader_keys_seen or menu not in leader_rows:
                continue
            leader_keys_seen.add(menu)
            label = _LEADER_MENU_LABELS.get(menu, f"Leader menu: {menu}")
            options.append(Option(f"── {label} ──", disabled=True))
            for row in leader_rows[menu]:
                options.append(self._build_option(row, len(visible)))
                visible.append(row)

        for state in sorted(action_rows.keys()):
            label = _STATE_LABELS.get(state, state)
            options.append(Option(f"── {label} ──", disabled=True))
            for row in action_rows[state]:
                options.append(self._build_option(row, len(visible)))
                visible.append(row)

        option_list.clear_options()
        if options:
            option_list.add_options(options)
        else:
            option_list.add_option(Option("(no bindings match filter)", disabled=True))

        self._visible_rows = visible
        self._update_filter_display()
        self._restore_highlight(option_list)

    def _build_option(self, row: _Row, visible_index: int) -> Option:
        keys_display = ", ".join(format_key(k) for k in row.current_keys) or "(unbound)"
        marker = " [yellow]*[/]" if row.is_customized else ""
        line = (
            f"  [bold $warning]{keys_display:<14}[/] {row.label}{marker}"
        )
        return Option(line, id=f"row-{visible_index}")

    def _move_highlight_to_first_row(self, option_list: OptionList) -> None:
        for i in range(option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
            except Exception:
                continue
            if not opt.disabled:
                option_list.highlighted = i
                self._last_highlight_identity = (
                    self._visible_rows[0].identity if self._visible_rows else None
                )
                return

    def _restore_highlight(self, option_list: OptionList) -> None:
        """Try to keep the highlight on the same row after a rebuild.

        After a rebind/revert the row order may stay the same but the
        OptionList index of a given row can shift (e.g. if filtering
        changed). Snap back to the same logical row when possible, else
        fall back to the first selectable row.
        """
        if self._last_highlight_identity is not None:
            for vis_idx, row in enumerate(self._visible_rows):
                if row.identity == self._last_highlight_identity:
                    self._highlight_visible(option_list, vis_idx)
                    return
        self._move_highlight_to_first_row(option_list)

    def _highlight_visible(self, option_list: OptionList, visible_index: int) -> None:
        try:
            target_id = f"row-{visible_index}"
            option_list.highlighted = option_list.get_option_index(target_id)
        except Exception:
            self._move_highlight_to_first_row(option_list)

    # ----------------------------------------------------- highlight helper

    def _current_row(self) -> _Row | None:
        try:
            option_list = self.query_one("#kb-list", OptionList)
        except Exception:
            return None
        idx = option_list.highlighted
        if idx is None:
            return None
        try:
            option = option_list.get_option_at_index(idx)
        except Exception:
            return None
        if option.id is None or not option.id.startswith("row-"):
            return None
        try:
            vis_idx = int(option.id[len("row-") :])
        except ValueError:
            return None
        if 0 <= vis_idx < len(self._visible_rows):
            return self._visible_rows[vis_idx]
        return None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != "kb-list":
            return
        row = self._current_row()
        if row is not None:
            self._last_highlight_identity = row.identity

    # ---------------------------------------------------------- actions

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_cursor_down(self) -> None:
        self._move_cursor(+1)

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)

    def _move_cursor(self, delta: int) -> None:
        """Step the OptionList highlight by ``delta``, skipping disabled
        section-header rows so j/k feel native."""
        try:
            option_list = self.query_one("#kb-list", OptionList)
        except Exception:
            return
        count = option_list.option_count
        if count == 0:
            return
        idx = option_list.highlighted
        if idx is None:
            idx = -1 if delta > 0 else count
        step = 1 if delta > 0 else -1
        i = idx + step
        while 0 <= i < count:
            try:
                if not option_list.get_option_at_index(i).disabled:
                    option_list.highlighted = i
                    option_list.scroll_to_highlight()
                    return
            except Exception:
                return
            i += step

    def action_rebind(self) -> None:
        row = self._current_row()
        if row is None:
            return
        label = f"{row.label}  ({self._scope_label(row)})"

        def on_key(new_key: str | None) -> None:
            if not new_key:
                return
            self._apply_rebind(row, new_key)

        self.app.push_screen(KeyCaptureScreen(label=label), on_key)

    def action_revert(self) -> None:
        row = self._current_row()
        if row is None:
            return
        if not row.is_customized:
            self._notify("Already at default", severity="information")
            return

        title = "Revert this binding?"
        description = (
            f"Reset [bold]{row.label}[/] to default "
            f"({', '.join(format_key(k) for k in row.default_keys) or 'unbound'})?"
        )

        def on_confirm(result: bool | None) -> None:
            if not result:
                return
            self._apply_revert(row)

        self.app.push_screen(_NarrowConfirmScreen(title, description), on_confirm)

    def action_reset_all(self) -> None:
        title = "Reset all keybindings?"
        description = "Wipe all customizations and restore defaults."

        def on_confirm(result: bool | None) -> None:
            if not result:
                return
            self._apply_reset_all()

        self.app.push_screen(_NarrowConfirmScreen(title, description), on_confirm)

    def action_open_filter(self) -> None:
        self._filter_active = True
        try:
            self.query_one("#kb-filter", FilterInput).show()
        except Exception:
            pass
        self._update_filter_display()

    def _close_filter(self) -> None:
        self._filter_active = False
        self._filter_text = ""
        try:
            self.query_one("#kb-filter", FilterInput).hide()
        except Exception:
            pass
        self._render_list()

    # ------------------------------------------------------ apply / persist

    def _apply_rebind(self, row: _Row, new_key: str) -> None:
        # Preserve aliases — the merge logic in KeymapManager replaces the
        # entire key list per (action, state). If we wrote just the new
        # key we'd silently drop default aliases (e.g. arrow-key aliases
        # for h/j/k/l), which would surprise the user.
        manager = self._manager()
        if manager is None:
            return

        try:
            if row.kind == "leader":
                manager.edit_leader_command(row.scope, row.action, new_key)
            else:
                # action_keys: keep existing aliases (everything after the
                # primary), put the new key first as the new primary.
                aliases = [k for k in row.current_keys[1:] if k != new_key]
                key_list: str | list[str] = (
                    [new_key, *aliases] if aliases else new_key
                )
                manager.edit_action_key(row.scope, row.action, key_list)
        except Exception as exc:
            self._restore_keymap_after_failure(exc)
            return

        self._republish_textual_keymap()
        self._notify(
            f"Bound {format_key(new_key)} → {row.label}", severity="information"
        )
        self._rebuild_rows()
        self._render_list()

    def _apply_revert(self, row: _Row) -> None:
        manager = self._manager()
        if manager is None:
            return
        try:
            if row.kind == "leader":
                manager.edit_leader_command(row.scope, row.action, None)
            else:
                manager.edit_action_key(row.scope, row.action, None)
        except Exception as exc:
            self._restore_keymap_after_failure(exc)
            return
        self._republish_textual_keymap()
        self._notify(f"Reverted {row.label}", severity="information")
        self._rebuild_rows()
        self._render_list()

    def _apply_reset_all(self) -> None:
        manager = self._manager()
        if manager is None:
            return
        try:
            manager.reset_all()
        except Exception as exc:
            self._restore_keymap_after_failure(exc)
            return
        self._republish_textual_keymap()
        self._notify("All keybindings reset to defaults", severity="information")
        self._rebuild_rows()
        self._render_list()

    def _republish_textual_keymap(self) -> None:
        """After set_keymap() updates the provider, Textual still needs
        the new key strings — push them via App.set_keymap so any Binding
        with an action ID picks them up."""
        from sqlit.core.keymap import build_textual_keymap, get_keymap as _get

        try:
            self.app.set_keymap(build_textual_keymap(_get()))
        except Exception:
            # Hot-update isn't critical — the next app start will reload
            # from disk anyway. Don't break the editor flow.
            pass

    def _restore_keymap_after_failure(self, exc: Exception) -> None:
        # KeymapManager.validate_payload() raises if the proposed edit
        # would conflict — the file isn't written, so the user's last
        # good keymap stays in effect. Surface the full multi-line
        # message in a modal so the user actually sees it, instead of
        # a fleeting toast that overlaps the results panel.
        from sqlit.shared.ui.screens.error import ErrorScreen

        message = str(exc).strip() or "Edit rejected"
        title = (
            "Keybinding conflict"
            if message.lower().startswith("conflicting keybindings")
            else "Keybinding edit failed"
        )
        self.app.push_screen(ErrorScreen(title, message))

    def _manager(self) -> Any:
        app = cast("SSMSTUI", self.app)
        manager = getattr(app, "_keymap_manager", None)
        if manager is None:
            self._notify(
                "Keymap manager not available — restart sqlit",
                severity="error",
            )
        return manager

    def _notify(self, message: str, *, severity: str = "information") -> None:
        try:
            self.app.notify(message, severity=severity)  # type: ignore[arg-type]
        except Exception:
            pass

    def _scope_label(self, row: _Row) -> str:
        if row.kind == "leader":
            return _LEADER_MENU_LABELS.get(row.scope, row.scope)
        return _STATE_LABELS.get(row.scope, row.scope)

    # ---------------------------------------------------------- key handling

    def on_key(self, event: events.Key) -> None:
        # Only intercept printable characters when filter is open — the
        # OptionList still owns j/k/arrows for navigation.
        if not self._filter_active:
            return
        key = event.key
        if key == "escape":
            self._close_filter()
            event.stop()
            return
        if key == "backspace":
            if self._filter_text:
                self._filter_text = self._filter_text[:-1]
                self._render_list()
            else:
                self._close_filter()
            event.stop()
            return
        if event.character and event.character.isprintable():
            if event.character == "/":
                # Already inside filter — swallow so it doesn't reopen.
                event.stop()
                return
            self._filter_text += event.character
            self._render_list()
            event.stop()

    def _update_filter_display(self) -> None:
        try:
            filter_input = self.query_one("#kb-filter", FilterInput)
        except Exception:
            return
        total = len(self._rows)
        if self._filter_text:
            filter_input.set_filter(self._filter_text, len(self._visible_rows), total)
        else:
            filter_input.set_filter("", 0, total)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Enter on a row triggers a rebind, same as the `r` shortcut.
        if event.option_list.id != "kb-list":
            return
        self.action_rebind()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # Standard guard so underlying screens don't react when a child
        # modal (KeyCaptureScreen / ConfirmScreen) is on top.
        if self.app.screen is not self:
            return False
        return super().check_action(action, parameters)
