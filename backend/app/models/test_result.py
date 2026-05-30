import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TestResult(Base):
    """Result for a single API request execution within a TestRun."""
    __tablename__ = "test_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    test_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("api_requests.id", ondelete="SET NULL"))
    # Snapshot preserves the exact request config used — stays accurate
    # even if the user edits the request after execution.
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)   # passed|failed|error|skipped
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_body: Mapped[str | None] = mapped_column(Text)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    test_run: Mapped["TestRun"] = relationship(back_populates="results", lazy="raise")  # noqa: F821
    assertion_results: Mapped[list["AssertionResult"]] = relationship(  # noqa: F821
        back_populates="test_result", cascade="all, delete-orphan", lazy="raise"
    )
    ai_analysis: Mapped["AiAnalysis | None"] = relationship(  # noqa: F821
        back_populates="test_result", cascade="all, delete-orphan", lazy="raise", uselist=False
    )
