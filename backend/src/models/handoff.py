from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.utils.time import now


class HandoffBatch(Base):
    """外站交接包里的原巡检批次，相同内容只保留一份。"""

    __tablename__ = 'handoff_batches'
    __table_args__ = (UniqueConstraint('batch_key'), UniqueConstraint('checksum'))

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(120))
    checksum: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int]
    rows: Mapped[list] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)


class HandoffReport(Base):
    """外站报告按“站点 + 报告号”保存；同号不同站各自保留。"""

    __tablename__ = 'handoff_reports'
    __table_args__ = (UniqueConstraint('station', 'report_no'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station: Mapped[str] = mapped_column(String(80))
    report_no: Mapped[str] = mapped_column(String(80))
    batch_id: Mapped[int] = mapped_column(ForeignKey('handoff_batches.id'))
    params: Mapped[dict] = mapped_column(JSON)
    rule_version: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), index=True)
    headline: Mapped[str] = mapped_column(String(500))
    result: Mapped[dict] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
