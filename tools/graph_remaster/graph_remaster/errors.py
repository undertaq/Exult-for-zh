"""Exceptions raised by the graph remaster package."""


class ConfigError(ValueError):
    """Raised when a pipeline configuration is missing or invalid."""


class InvalidStateTransition(ValueError):
    """Raised when a job state change is not an allowed compare-and-set."""


class MigrationError(RuntimeError):
    """Raised when a database migration cannot preserve its existing state."""


class SourceToolError(RuntimeError):
    """A source adapter command or PNG inspection failure with command output."""

    def __init__(
        self,
        message: str,
        *,
        command: tuple[str, ...] = (),
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
