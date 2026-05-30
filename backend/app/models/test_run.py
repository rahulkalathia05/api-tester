import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TestRun(Base):
    """
    A single execution of a collection (or single request).

    status lifecycle:  pending → running → passed | failed | error
    """
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("collections.id", ondelete="SET NULL"), index=True)
    environment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("environments.id", ondelete="SET NULL"))
    triggered_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"))
    trigger_type: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)   # manual|scheduled|api
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {retry_count, stop_on_failure}

    workspace: Mapped["Workspace"] = relationship(back_populates="test_runs", lazy="raise")  # noqa: F821
    results: Mapped[list["TestResult"]] = relationship(  # noqa: F821
        back_populates="test_run", cascade="all, delete-orphan", lazy="raise"
    )
