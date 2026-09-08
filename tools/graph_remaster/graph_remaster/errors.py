"""Exceptions raised by the graph remaster package."""


class ConfigError(ValueError):
    """Raised when a pipeline configuration is missing or invalid."""


class InvalidStateTransition(ValueError):
    """Raised when a job state change is not an allowed compare-and-set."""
