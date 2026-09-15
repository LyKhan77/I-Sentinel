"""Zone analyzers. New analyzer = one file + one ANALYZERS entry."""
from .base import Analyzer
from .intrusion import IntrusionAnalyzer, point_in_polygon

ANALYZERS = {"intrusion": IntrusionAnalyzer}

__all__ = ["Analyzer", "ANALYZERS", "IntrusionAnalyzer", "point_in_polygon"]
