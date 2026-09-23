"""Zone analyzers. New analyzer = one file + one ANALYZERS entry."""
from .base import Analyzer
from .intrusion import IntrusionAnalyzer, ground_point, point_in_polygon
from .loitering import LoiteringAnalyzer
from .running import RunningAnalyzer

ANALYZERS = {"intrusion": IntrusionAnalyzer, "loitering": LoiteringAnalyzer,
             "running": RunningAnalyzer}

__all__ = ["Analyzer", "ANALYZERS", "IntrusionAnalyzer", "LoiteringAnalyzer",
           "RunningAnalyzer", "point_in_polygon", "ground_point"]
