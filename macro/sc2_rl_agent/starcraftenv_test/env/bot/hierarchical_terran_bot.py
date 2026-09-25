"""Astra strategy + Jev immediate macro choices + the Terran SC2 executor."""

from .hierarchical_bot import HierarchicalMixin
from .jev_terran_bot import JevTerranBot


class HierarchicalTerranBot(HierarchicalMixin, JevTerranBot):
    pass
