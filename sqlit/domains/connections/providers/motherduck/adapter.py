"""MotherDuck adapter for cloud DuckDB."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlit.domains.connections.providers.duckdb.adapter import DuckDBAdapter

if TYPE_CHECKING:
    from sqlit.domains.connections.domain.config import ConnectionConfig


class MotherDuckAdapter(DuckDBAdapter):
    """Adapter for MotherDuck cloud DuckDB service."""

    @property
    def name(self) -> str:
        return "MotherDuck"

    @property
    def supports_process_worker(self) -> bool:
        """MotherDuck handles concurrency server-side."""
        return True

    def connect(self, config: ConnectionConfig) -> Any:
        """Connect to MotherDuck cloud database.

        Connection string format: md:[database_name][?motherduck_token=TOKEN]
        If no token is provided, browser-based authentication is used.
        """
        duckdb = self._import_driver_module(
            "duckdb",
            driver_name=self.name,
            extra_name=self.install_extra,
            package_name=self.install_package,
        )

        # Build MotherDuck connection string
        database = config.get_option("database", "") or config.database or ""
        token = config.get_option("motherduck_token", "")

        conn_str = f"md:{database}" if database else "md:"
        if token:
            conn_str += f"?motherduck_token={token}"

        duckdb_any: Any = duckdb
        return duckdb_any.connect(conn_str)
