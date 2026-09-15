"""Zone analyzers. New analyzer = one file + one ANALYZERS entry."""
from .base import Analyzer
from .intrusion import IntrusionAnalyzer, point_in_polygon
from .loitering import LoiteringAnalyzer

ANALYZERS = {"intrusion": IntrusionAnalyzer, "loitering": LoiteringAnalyzer}

__all__ = ["Analyzer", "ANALYZERS", "IntrusionAnalyzer", "LoiteringAnalyzer", "point_in_polygon"]
