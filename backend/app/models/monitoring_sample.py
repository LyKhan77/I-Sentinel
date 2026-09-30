from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MonitoringSample(Base):
    """Satu menit metrik satu node (agregat heartbeat) — riwayat grafik tren, dipangkas setelah 7 hari."""
    __tablename__ = "monitoring_sample"
    __table_args__ = (UniqueConstraint("node_id", "ts", name="uq_monitoring_sample_node_ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("node.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSON)
