"""Zone analyzers. New analyzer = one file + one ANALYZERS entry."""
from .base import Analyzer
from .face_gate import FaceGateAnalyzer, crop_upper_body
from .intrusion import IntrusionAnalyzer, point_in_polygon
from .loitering import LoiteringAnalyzer
from .running import RunningAnalyzer

ANALYZERS = {"intrusion": IntrusionAnalyzer, "loitering": LoiteringAnalyzer,
             "running": RunningAnalyzer, "face_gate": FaceGateAnalyzer}

__all__ = ["Analyzer", "ANALYZERS", "IntrusionAnalyzer", "LoiteringAnalyzer",
           "RunningAnalyzer", "FaceGateAnalyzer", "crop_upper_body",
           "point_in_polygon"]
