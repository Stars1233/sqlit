"""PostgreSQL adapter using psycopg2."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..schema import get_default_port
from .base import PostgresBaseAdapter, import_driver_module

if TYPE_CHECKING:
    from ...config import ConnectionConfig


class PostgreSQLAdapter(PostgresBaseAdapter):
    """Adapter for PostgreSQL using psycopg2."""

    @classmethod
    def badge_label(cls) -> str:
        return "PG"

    @classmethod
    def url_schemes(cls) -> tuple[str, ...]:
        return ("postgresql", "postgres")

    @classmethod
    def docker_image_patterns(cls) -> tuple[str, ...]:
        return ("postgres",)

    @classmethod
    def docker_env_vars(cls) -> dict[str, tuple[str, ...]]:
        return {
            "user": ("POSTGRES_USER",),
            "password": ("POSTGRES_PASSWORD",),
            "database": ("POSTGRES_DB",),
        }

    @classmethod
    def docker_default_user(cls) -> str | None:
        return "postgres"

    @classmethod
    def docker_default_database(cls) -> str | None:
        return "postgres"

    @property
    def name(self) -> str:
        return "PostgreSQL"

    @property
    def install_extra(self) -> str:
        return "postgres"

    @property
    def install_package(self) -> str:
        return "psycopg2-binary"

    @property
    def driver_import_names(self) -> tuple[str, ...]:
        return ("psycopg2",)

    def connect(self, config: ConnectionConfig) -> Any:
        """Connect to PostgreSQL database."""
        psycopg2 = import_driver_module(
            "psycopg2",
            driver_name=self.name,
            extra_name=self.install_extra,
            package_name=self.install_package,
        )

        port = int(config.port or get_default_port("postgresql"))
        conn = psycopg2.connect(
            host=config.server,
            port=port,
            database=config.database or "postgres",
            user=config.username,
            password=config.password,
            connect_timeout=10,
        )
        # Enable autocommit to avoid "transaction aborted" errors on failed statements
        conn.autocommit = True
        return conn

    def get_databases(self, conn: Any) -> list[str]:
        """Get list of databases from PostgreSQL."""
        cursor = conn.cursor()
        cursor.execute("SELECT datname FROM pg_database " "WHERE datistemplate = false ORDER BY datname")
        return [row[0] for row in cursor.fetchall()]

    def get_procedures(self, conn: Any, database: str | None = None) -> list[str]:
        """Get stored procedures/functions from PostgreSQL."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT routine_name FROM information_schema.routines "
            "WHERE routine_schema = 'public' AND routine_type = 'FUNCTION' "
            "ORDER BY routine_name"
        )
        return [row[0] for row in cursor.fetchall()]
