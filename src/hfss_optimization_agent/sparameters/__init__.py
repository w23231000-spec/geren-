"""Fast S-parameter providers for offline tests and supplied-model integration."""

from .mock_surrogate import DeterministicSurrogate
from .supplied_adapter import SuppliedSurrogateAdapter, SuppliedSurrogateConfig

__all__ = ["DeterministicSurrogate", "SuppliedSurrogateAdapter", "SuppliedSurrogateConfig"]
