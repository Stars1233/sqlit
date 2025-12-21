"""Error handling strategies for connection failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING, Any

from ..protocols import AppProtocol

if TYPE_CHECKING:
    from ...config import ConnectionConfig


class ConnectionErrorHandler(Protocol):
    def can_handle(self, error: Exception) -> bool:
        """Return True if this handler can handle the error."""

    def handle(self, app: AppProtocol, error: Exception, config: ConnectionConfig) -> None:
        """Handle the error."""


@dataclass(frozen=True)
class MissingDriverHandler:
    def can_handle(self, error: Exception) -> bool:
        from ...db.exceptions import MissingDriverError

        return isinstance(error, MissingDriverError)

    def handle(self, app: AppProtocol, error: Exception, config: ConnectionConfig) -> None:
        from ...services.installer import Installer
        from ..screens import PackageSetupScreen

        app.push_screen(
            PackageSetupScreen(error, on_install=lambda err: Installer(app).install(err)),
        )


@dataclass(frozen=True)
class MissingOdbcDriverHandler:
    def can_handle(self, error: Exception) -> bool:
        from ...db.exceptions import MissingODBCDriverError

        return isinstance(error, MissingODBCDriverError)

    def handle(self, app: AppProtocol, error: Exception, config: ConnectionConfig) -> None:
        from ...config import save_connections
        from ...terminal import run_in_terminal
        from ..screens import ConfirmScreen, DriverSetupScreen, MessageScreen

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed is not True:
                app.push_screen(
                    MessageScreen(
                        "Missing ODBC driver",
                        (
                            "SQL Server requires an ODBC driver.\n\n"
                            "Open connection settings (Advanced) to configure drivers."
                        ),
                    )
                )
                return

            def on_driver_result(result: Any) -> None:
                if not result:
                    return
                action = result[0]
                if action == "select":
                    driver = result[1]
                    config.set_option("driver", driver)
                    for i, c in enumerate(app.connections):
                        if c.name == config.name:
                            app.connections[i] = config
                            break
                    save_connections(app.connections)
                    connect = getattr(app, "connect_to_server", None)
                    if callable(connect):
                        app.call_later(lambda: connect(config))
                    return
                if action == "install":
                    commands = result[1]
                    res = run_in_terminal(commands)
                    if res.success:
                        app.push_screen(
                            MessageScreen(
                                "Driver install",
                                "Installation started in a new terminal.\n\nPlease restart to apply.",
                            )
                        )
                    else:
                        app.push_screen(
                            MessageScreen(
                                "Couldn't install automatically",
                                "Couldn't install automatically, please install manually.",
                            ),
                            lambda _=None: app.push_screen(
                                DriverSetupScreen(error.installed_drivers), on_driver_result
                            ),
                        )

            app.push_screen(DriverSetupScreen(error.installed_drivers), on_driver_result)

        app.push_screen(
            ConfirmScreen(
                "Missing ODBC driver",
                "SQL Server requires an ODBC driver.\n\nOpen driver setup now?",
            ),
            on_confirm,
        )


_DEFAULT_HANDLERS: tuple[ConnectionErrorHandler, ...] = (
    MissingDriverHandler(),
    MissingOdbcDriverHandler(),
)


def handle_connection_error(app: AppProtocol, error: Exception, config: ConnectionConfig) -> bool:
    for handler in _DEFAULT_HANDLERS:
        if handler.can_handle(error):
            handler.handle(app, error, config)
            return True
    return False
