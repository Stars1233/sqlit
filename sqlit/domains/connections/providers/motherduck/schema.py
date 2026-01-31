"""Connection schema for MotherDuck."""

from sqlit.domains.connections.providers.schema_helpers import (
    ConnectionSchema,
    FieldType,
    SchemaField,
)

SCHEMA = ConnectionSchema(
    db_type="motherduck",
    display_name="MotherDuck",
    fields=(
        SchemaField(
            name="database",
            label="Database",
            placeholder="my_database (optional)",
            required=False,
            description="MotherDuck database name. Leave empty to use default.",
        ),
        SchemaField(
            name="motherduck_token",
            label="Access Token",
            field_type=FieldType.PASSWORD,
            placeholder="(optional - uses browser auth if empty)",
            required=False,
            description="MotherDuck access token for non-interactive authentication.",
        ),
    ),
    supports_ssh=False,
    is_file_based=False,
    requires_auth=False,
)
