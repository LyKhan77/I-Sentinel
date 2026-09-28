"""Zone analyzers. New analyzer = one file + one ANALYZERS entry."""
from .base import Analyzer
from .crowd import CrowdAnalyzer
from .idle_zone import IdleZoneAnalyzer
from .intrusion import IntrusionAnalyzer, ground_point, point_in_polygon
from .loitering import LoiteringAnalyzer
from .running import RunningAnalyzer

ANALYZERS = {"intrusion": IntrusionAnalyzer, "loitering": LoiteringAnalyzer,
             "running": RunningAnalyzer, "idle_zone": IdleZoneAnalyzer, "crowd": CrowdAnalyzer}

__all__ = ["Analyzer", "ANALYZERS", "IntrusionAnalyzer", "LoiteringAnalyzer",
           "RunningAnalyzer", "IdleZoneAnalyzer", "CrowdAnalyzer", "point_in_polygon", "ground_point"]
