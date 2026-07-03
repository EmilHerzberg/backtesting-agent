"""Singleton registry for backtesting indicators."""

from __future__ import annotations

from typing import Any

from src.backend.backtesting.indicators.base import BacktestIndicator


class BacktestIndicatorRegistry:
    """Singleton registry that maps indicator names to their classes.

    Usage::

        registry = BacktestIndicatorRegistry()
        registry.register("SMA", SMAIndicator)
        indicator = registry.get("SMA", period=20)
    """

    _instance: BacktestIndicatorRegistry | None = None
    _registry: dict[str, type[BacktestIndicator]]

    def __new__(cls) -> BacktestIndicatorRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._registry = {}
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, name: str, cls: type[BacktestIndicator]) -> None:
        """Register an indicator class under *name* (case-insensitive key)."""
        self._registry[name.upper()] = cls

    def get(self, name: str, **params: Any) -> BacktestIndicator:
        """Instantiate a registered indicator with the given parameters.

        Raises:
            KeyError: If *name* is not registered.
        """
        key = name.upper()
        if key not in self._registry:
            available = ", ".join(sorted(self._registry))
            raise KeyError(
                f"Unknown backtesting indicator '{name}'. "
                f"Available: {available}"
            )
        return self._registry[key](**params)

    def list_all(self) -> list[str]:
        """Return sorted list of all registered indicator names."""
        return sorted(self._registry)

    def get_parameter_space(self, name: str) -> dict[str, dict[str, Any]]:
        """Return the Optuna parameter space for a registered indicator.

        Creates a default-parameter instance to call ``parameter_space()``.

        Raises:
            KeyError: If *name* is not registered.
        """
        key = name.upper()
        if key not in self._registry:
            available = ", ".join(sorted(self._registry))
            raise KeyError(
                f"Unknown backtesting indicator '{name}'. "
                f"Available: {available}"
            )
        # Instantiate with defaults to read the space definition
        instance = self._registry[key]()
        return instance.parameter_space()


# Module-level convenience instance
registry = BacktestIndicatorRegistry()
