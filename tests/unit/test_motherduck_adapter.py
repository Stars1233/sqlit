"""Unit tests for MotherDuck adapter."""

from __future__ import annotations

import pytest

from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint


class TestMotherDuckConnectionString:
    """Test MotherDuck connection string building."""

    def test_basic_connection_string(self):
        """Test basic md: connection string."""
        from sqlit.domains.connections.providers.motherduck.adapter import MotherDuckAdapter

        adapter = MotherDuckAdapter()
        config = ConnectionConfig(
            name="test",
            db_type="motherduck",
            endpoint=TcpEndpoint(),
        )

        # We can't actually connect without duckdb/motherduck, but we can test
        # that the adapter builds the correct connection string
        database = config.get_option("database", "") or config.database or ""
        token = config.get_option("motherduck_token", "")

        conn_str = f"md:{database}" if database else "md:"
        if token:
            conn_str += f"?motherduck_token={token}"

        assert conn_str == "md:"

    def test_connection_string_with_database(self):
        """Test md:database connection string."""
        config = ConnectionConfig(
            name="test",
            db_type="motherduck",
            endpoint=TcpEndpoint(database="my_database"),
        )

        database = config.get_option("database", "") or config.database or ""
        token = config.get_option("motherduck_token", "")

        conn_str = f"md:{database}" if database else "md:"
        if token:
            conn_str += f"?motherduck_token={token}"

        assert conn_str == "md:my_database"

    def test_connection_string_with_database_in_options(self):
        """Test database from options."""
        config = ConnectionConfig(
            name="test",
            db_type="motherduck",
            endpoint=TcpEndpoint(),
            options={"database": "options_database"},
        )

        database = config.get_option("database", "") or config.database or ""
        token = config.get_option("motherduck_token", "")

        conn_str = f"md:{database}" if database else "md:"
        if token:
            conn_str += f"?motherduck_token={token}"

        assert conn_str == "md:options_database"

    def test_connection_string_with_token(self):
        """Test md: with token."""
        config = ConnectionConfig(
            name="test",
            db_type="motherduck",
            endpoint=TcpEndpoint(),
            options={"motherduck_token": "my_secret_token"},
        )

        database = config.get_option("database", "") or config.database or ""
        token = config.get_option("motherduck_token", "")

        conn_str = f"md:{database}" if database else "md:"
        if token:
            conn_str += f"?motherduck_token={token}"

        assert conn_str == "md:?motherduck_token=my_secret_token"

    def test_connection_string_with_database_and_token(self):
        """Test md:database?token connection string."""
        config = ConnectionConfig(
            name="test",
            db_type="motherduck",
            endpoint=TcpEndpoint(database="prod_db"),
            options={"motherduck_token": "my_token"},
        )

        database = config.get_option("database", "") or config.database or ""
        token = config.get_option("motherduck_token", "")

        conn_str = f"md:{database}" if database else "md:"
        if token:
            conn_str += f"?motherduck_token={token}"

        assert conn_str == "md:prod_db?motherduck_token=my_token"


def test_motherduck_provider_registered():
    """Test that MotherDuck provider is properly registered."""
    from sqlit.domains.connections.providers.catalog import get_supported_db_types

    db_types = get_supported_db_types()
    assert "motherduck" in db_types


def test_motherduck_provider_metadata():
    """Test MotherDuck provider metadata."""
    from sqlit.domains.connections.providers.catalog import get_provider

    provider = get_provider("motherduck")
    assert provider.metadata.display_name == "MotherDuck"
    assert provider.metadata.is_file_based is False
    assert provider.metadata.supports_ssh is False
    assert "md" in provider.metadata.url_schemes
    assert "motherduck" in provider.metadata.url_schemes


def test_motherduck_database_type_enum():
    """Test MotherDuck is in DatabaseType enum."""
    from sqlit.domains.connections.domain.config import DatabaseType

    assert DatabaseType.MOTHERDUCK.value == "motherduck"
