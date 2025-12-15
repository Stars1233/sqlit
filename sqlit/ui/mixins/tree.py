"""Tree/Explorer mixin for SSMSTUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Tree

if TYPE_CHECKING:
    from ...config import ConnectionConfig
    from ...services import ConnectionSession


class TreeMixin:
    """Mixin providing tree/explorer functionality."""

    # These attributes are defined in the main app class
    connections: list
    current_connection: Any
    current_config: "ConnectionConfig | None"
    current_adapter: Any
    _expanded_paths: set[str]
    _session: "ConnectionSession | None"
    _loading_nodes: set

    def _db_type_badge(self, db_type: str) -> str:
        """Get short badge for database type."""
        badge_map = {
            "mssql": "MSSQL",
            "postgresql": "PG",
            "mysql": "MySQL",
            "mariadb": "MariaDB",
            "sqlite": "SQLite",
            "oracle": "Oracle",
            "duckdb": "DuckDB",
            "cockroachdb": "CRDB",
            "turso": "Turso",
        }
        return badge_map.get(db_type, db_type.upper() if db_type else "DB")

    def refresh_tree(self) -> None:
        """Refresh the explorer tree."""
        self.object_tree.clear()
        self.object_tree.root.expand()

        for conn in self.connections:
            display_info = conn.get_display_info()
            db_type_label = self._db_type_badge(conn.db_type)
            node = self.object_tree.root.add(
                f"[dim]{conn.name}[/dim] [{db_type_label}] ({display_info})"
            )
            node.data = ("connection", conn)
            node.allow_expand = True

        if self.current_connection and self.current_config:
            self.populate_connected_tree()

    def populate_connected_tree(self) -> None:
        """Populate tree with database objects when connected."""
        if not self.current_connection or not self.current_config or not self.current_adapter:
            return

        adapter = self.current_adapter

        def get_conn_label(config, connected=False):
            display_info = config.get_display_info()
            db_type_label = self._db_type_badge(config.db_type)
            if connected:
                name = f"[green]{config.name}[/green]"
            else:
                name = config.name
            return f"{name} [{db_type_label}] ({display_info})"

        active_node = None
        for child in self.object_tree.root.children:
            if child.data and child.data[0] == "connection":
                if child.data[1].name == self.current_config.name:
                    child.set_label(get_conn_label(self.current_config, connected=True))
                    active_node = child
                    break

        if not active_node:
            active_node = self.object_tree.root.add(
                get_conn_label(self.current_config, connected=True)
            )
            active_node.data = ("connection", self.current_config)

        active_node.remove_children()

        try:
            if adapter.supports_multiple_databases:
                specific_db = self.current_config.database
                if specific_db and specific_db.lower() not in ("", "master"):
                    self._add_database_object_nodes(active_node, specific_db)
                    active_node.expand()
                else:
                    dbs_node = active_node.add("Databases")
                    dbs_node.data = ("folder", "databases")

                    databases = adapter.get_databases(self.current_connection)
                    for db_name in databases:
                        db_node = dbs_node.add(db_name)
                        db_node.data = ("database", db_name)
                        db_node.allow_expand = True
                        self._add_database_object_nodes(db_node, db_name)

                    active_node.expand()
                    dbs_node.expand()
            else:
                self._add_database_object_nodes(active_node, None)
                active_node.expand()

            self.call_later(lambda: self._restore_subtree_expansion(active_node))

        except Exception as e:
            self.notify(f"Error loading objects: {e}", severity="error")

    def _add_database_object_nodes(self, parent_node, database: str | None) -> None:
        """Add Tables, Views, and optionally Stored Procedures nodes."""
        tables_node = parent_node.add("Tables")
        tables_node.data = ("folder", "tables", database)
        tables_node.allow_expand = True

        views_node = parent_node.add("Views")
        views_node.data = ("folder", "views", database)
        views_node.allow_expand = True

        if self.current_adapter and self.current_adapter.supports_stored_procedures:
            procs_node = parent_node.add("Stored Procedures")
            procs_node.data = ("folder", "procedures", database)
            procs_node.allow_expand = True

    def _get_node_path(self, node) -> str:
        """Get a unique path string for a tree node."""
        parts = []
        current = node
        while current and current.parent:
            if current.data:
                data = current.data
                if data[0] == "connection":
                    parts.append(f"conn:{data[1].name}")
                elif data[0] == "database":
                    parts.append(f"db:{data[1]}")
                elif data[0] == "folder":
                    parts.append(f"folder:{data[1]}")
                elif data[0] in ("table", "view") and len(data) >= 4:
                    # Include schema in path for uniqueness
                    schema_name = data[2]
                    obj_name = data[3]
                    parts.append(f"{data[0]}:{schema_name}.{obj_name}")
            current = current.parent
        return "/".join(reversed(parts))

    def _restore_subtree_expansion(self, node) -> None:
        """Recursively expand nodes that should be expanded."""
        for child in node.children:
            if child.data:
                path = self._get_node_path(child)
                if path in self._expanded_paths:
                    child.expand()
            self._restore_subtree_expansion(child)

    def _save_expanded_state(self) -> None:
        """Save which nodes are expanded."""
        from ...config import load_settings, save_settings

        expanded = []

        def collect_expanded(node):
            if node.is_expanded and node.data:
                path = self._get_node_path(node)
                if path:
                    expanded.append(path)
            for child in node.children:
                collect_expanded(child)

        collect_expanded(self.object_tree.root)

        self._expanded_paths = set(expanded)
        settings = load_settings()
        settings["expanded_nodes"] = expanded
        save_settings(settings)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        """Save state when a node is collapsed."""
        self.call_later(self._save_expanded_state)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Load child objects when a node is expanded."""
        node = event.node

        self.call_later(self._save_expanded_state)

        if not node.data or not self.current_connection or not self.current_adapter:
            return

        data = node.data

        # Skip if already has children (not just loading placeholder)
        children = list(node.children)
        if children:
            # Check if it's just a loading placeholder
            if len(children) == 1 and children[0].data == ("loading",):
                return  # Already loading
            if children[0].data != ("loading",):
                return  # Already loaded

        # Initialize _loading_nodes if not present
        if not hasattr(self, "_loading_nodes") or self._loading_nodes is None:
            self._loading_nodes = set()

        # Get node path to track loading state
        node_path = self._get_node_path(node)
        if node_path in self._loading_nodes:
            return  # Already loading this node

        # Handle table/view column expansion
        if data[0] in ("table", "view") and len(data) >= 4:
            self._loading_nodes.add(node_path)
            loading_node = node.add_leaf("[dim italic]Loading...[/]")
            loading_node.data = ("loading",)
            self._load_columns_async(node, data)
            return

        # Handle folder expansion
        if data[0] == "folder" and len(data) >= 3:
            self._loading_nodes.add(node_path)
            loading_node = node.add_leaf("[dim italic]Loading...[/]")
            loading_node.data = ("loading",)
            self._load_folder_async(node, data)
            return

    def _load_columns_async(self, node, data: tuple) -> None:
        """Spawn worker to load columns for a table/view."""
        db_name = data[1]
        schema_name = data[2]
        obj_name = data[3]

        def work() -> None:
            """Run in worker thread."""
            try:
                if not self._session:
                    columns = []
                else:
                    adapter = self._session.adapter
                    conn = self._session.connection
                    columns = adapter.get_columns(conn, obj_name, db_name, schema_name)

                # Update UI from worker thread
                self.call_from_thread(self._on_columns_loaded, node, db_name, schema_name, obj_name, columns)
            except Exception as e:
                self.call_from_thread(self._on_tree_load_error, node, f"Error loading columns: {e}")

        self.run_worker(work, name=f"load-columns-{obj_name}", thread=True, exclusive=False)

    def _on_columns_loaded(self, node, db_name: str, schema_name: str, obj_name: str, columns: list) -> None:
        """Handle column load completion on main thread."""
        node_path = self._get_node_path(node)
        self._loading_nodes.discard(node_path)

        # Remove loading placeholder
        for child in list(node.children):
            if child.data == ("loading",):
                child.remove()

        # Add column nodes
        for col in columns:
            child = node.add_leaf(f"[dim]{col.name}[/] [italic dim]{col.data_type}[/]")
            child.data = ("column", db_name, schema_name, obj_name, col.name)

    def _load_folder_async(self, node, data: tuple) -> None:
        """Spawn worker to load folder contents (tables/views/procedures)."""
        folder_type = data[1]
        db_name = data[2]

        def work() -> None:
            """Run in worker thread."""
            try:
                if not self._session:
                    items = []
                else:
                    adapter = self._session.adapter
                    conn = self._session.connection

                    if folder_type == "tables":
                        items = [("table", s, t) for s, t in adapter.get_tables(conn, db_name)]
                    elif folder_type == "views":
                        items = [("view", s, v) for s, v in adapter.get_views(conn, db_name)]
                    elif folder_type == "procedures":
                        if adapter.supports_stored_procedures:
                            items = [("procedure", p) for p in adapter.get_procedures(conn, db_name)]
                        else:
                            items = []
                    else:
                        items = []

                # Update UI from worker thread
                self.call_from_thread(self._on_folder_loaded, node, db_name, folder_type, items)
            except Exception as e:
                self.call_from_thread(self._on_tree_load_error, node, f"Error loading: {e}")

        self.run_worker(work, name=f"load-folder-{folder_type}", thread=True, exclusive=False)

    def _on_folder_loaded(self, node, db_name: str | None, folder_type: str, items: list) -> None:
        """Handle folder load completion on main thread."""
        node_path = self._get_node_path(node)
        self._loading_nodes.discard(node_path)

        # Remove loading placeholder
        for child in list(node.children):
            if child.data == ("loading",):
                child.remove()

        if not self._session:
            return

        adapter = self._session.adapter

        # Add nodes based on type
        for item in items:
            if item[0] == "table":
                schema_name, table_name = item[1], item[2]
                display_name = adapter.format_table_name(schema_name, table_name)
                child = node.add(display_name)
                child.data = ("table", db_name, schema_name, table_name)
                child.allow_expand = True
            elif item[0] == "view":
                schema_name, view_name = item[1], item[2]
                display_name = adapter.format_table_name(schema_name, view_name)
                child = node.add(display_name)
                child.data = ("view", db_name, schema_name, view_name)
                child.allow_expand = True
            elif item[0] == "procedure":
                proc_name = item[1]
                child = node.add(proc_name)
                child.data = ("procedure", db_name, proc_name)

    def _on_tree_load_error(self, node, error_message: str) -> None:
        """Handle tree load error on main thread."""
        node_path = self._get_node_path(node)
        self._loading_nodes.discard(node_path)

        # Remove loading placeholder
        for child in list(node.children):
            if child.data == ("loading",):
                child.remove()

        self.notify(error_message, severity="error")

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tree node selection (double-click/enter)."""
        node = event.node
        if not node.data:
            return

        data = node.data

        if data[0] == "connection":
            config = data[1]
            if self.current_config and self.current_config.name == config.name:
                return
            if self.current_connection:
                self._disconnect_silent()
            self.connect_to_server(config)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Update footer when tree selection changes."""
        self._update_footer_bindings()

    def action_refresh_tree(self) -> None:
        """Refresh the explorer."""
        self.refresh_tree()
        self.notify("Refreshed")

    def action_collapse_tree(self) -> None:
        """Collapse all nodes in the explorer."""
        def collapse_all(node):
            for child in node.children:
                collapse_all(child)
                child.collapse()

        collapse_all(self.object_tree.root)
        self._expanded_paths.clear()
        self._save_expanded_state()

    def action_select_table(self) -> None:
        """Generate and execute SELECT query for selected table/view."""
        if not self.current_adapter:
            return

        node = self.object_tree.cursor_node

        if not node or not node.data:
            return

        data = node.data
        if data[0] not in ("table", "view") or len(data) < 4:
            return

        db_name = data[1]
        schema_name = data[2]
        obj_name = data[3]
        self.query_input.text = self.current_adapter.build_select_query(obj_name, 100, db_name, schema_name)
        self.action_execute_query()
