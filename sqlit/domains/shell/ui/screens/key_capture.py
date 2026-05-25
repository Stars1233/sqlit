"""Captures the next key press for the in-app keybinding editor."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from sqlit.shared.ui.widgets import Dialog

# Modifier-only key events we want to ignore — the user is mid-chord, not
# trying to bind "ctrl by itself." Textual emits these as standalone events
# while the modifier is held before the second key arrives.
_MODIFIER_ONLY_KEYS = frozenset({"shift", "ctrl", "alt", "meta", "super", "cmd"})


class KeyCaptureScreen(ModalScreen[str | None]):
    """Modal that returns the next pressed key as a Textual key string.

    Dismisses with ``None`` on Escape (cancel), or with the captured key
    string (e.g. ``"j"``, ``"ctrl+s"``, ``"f5"``) when the user presses
    something rebindable.
    """

    CSS = """
    KeyCaptureScreen {
        align: center middle;
        background: transparent;
    }

    #key-capture-dialog {
        width: 50;
        height: auto;
    }

    #key-capture-message {
        margin: 1 1;
        height: auto;
    }
    """

    def __init__(self, *, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        shortcuts = [("Cancel", "<esc>")]
        with Dialog(id="key-capture-dialog", title="Press a key", shortcuts=shortcuts):
            yield Static(
                f"Press a key to bind to:\n  [bold]{self._label}[/]\n\n"
                "[dim]ESC to cancel.[/]",
                id="key-capture-message",
                markup=True,
            )

    def on_key(self, event: events.Key) -> None:
        # The user genuinely cannot bind to bare "escape" via this dialog —
        # we treat ESC as cancel so they can always back out. If they need
        # to bind escape itself, they can edit keymap.json directly.
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
            return

        if event.key in _MODIFIER_ONLY_KEYS:
            # Wait for the actual key — ctrl-by-itself isn't bindable.
            event.stop()
            return

        event.stop()
        self.dismiss(event.key)
