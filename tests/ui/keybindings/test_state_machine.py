"""Tests for state machine action validation."""

from __future__ import annotations

from sqlit.state_machine import UIStateMachine
from sqlit.widgets import VimMode


class TestStateMachineActionValidation:
    """Test that the state machine correctly validates actions."""

    def test_edit_connection_only_allowed_on_connection_node(self):
        """edit_connection should only be allowed when tree is on a connection."""

        class MockNode:
            def __init__(self, data=None):
                self.data = data

        class MockWidget:
            has_focus = False
            cursor_node = None
            root = MockNode()

        class MockApp:
            def __init__(self):
                self._leader_pending = False
                self.current_connection = None
                self.current_config = None
                self.screen_stack = [None]

            object_tree = MockWidget()
            query_input = MockWidget()
            results_table = MockWidget()

            @property
            def vim_mode(self):
                return VimMode.NORMAL

        sm = UIStateMachine()
        app = MockApp()

        # Query focused - edit_connection should be blocked
        app.query_input.has_focus = True
        app.object_tree.has_focus = False
        assert sm.check_action(app, "edit_connection") is False

        # Tree focused but not on connection - blocked
        app.query_input.has_focus = False
        app.object_tree.has_focus = True
        app.object_tree.cursor_node = MockNode(data=("table", "users"))
        assert sm.check_action(app, "edit_connection") is False

        # Tree focused on connection - allowed
        app.object_tree.cursor_node = MockNode(data=("connection", None))
        assert sm.check_action(app, "edit_connection") is True
