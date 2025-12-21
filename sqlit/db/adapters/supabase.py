from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .postgresql import PostgreSQLAdapter

if TYPE_CHECKING:
    from ...config import ConnectionConfig


class SupabaseAdapter(PostgreSQLAdapter):
    @classmethod
    def badge_label(cls) -> str:
        return "Supabase"

    @property
    def name(self) -> str:
        return "Supabase"

    @property
    def supports_multiple_databases(self) -> bool:
        return False

    def get_display_info(self, config: ConnectionConfig) -> str:
        region = config.get_option("supabase_region", "")
        return f"{config.name} ({region})"

    def connect(self, config: ConnectionConfig) -> Any:
        from dataclasses import replace

        region = config.get_option("supabase_region", "")
        project_id = config.get_option("supabase_project_id", "")
        transformed = replace(
            config,
            server=f"aws-0-{region}.pooler.supabase.com",
            port="5432",
            username=f"postgres.{project_id}",
            database="postgres",
        )
        return super().connect(transformed)
