"""Astra strategy + Jev immediate macro choices + the original Protoss SC2 executor."""

from .hierarchical_bot import HierarchicalMixin
from .jev_protoss_bot import JevProtossBot


class HierarchicalProtossBot(HierarchicalMixin, JevProtossBot):
    pass
