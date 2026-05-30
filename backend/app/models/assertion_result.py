import uuid

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssertionResult(Base):
    __tablename__ = "assertion_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    test_result_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False, index=True)
    assertion_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("assertions.id", ondelete="SET NULL"))
    # Snapshot so results remain accurate if the assertion is later edited.
    assertion_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actual_value: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    test_result: Mapped["TestResult"] = relationship(back_populates="assertion_results", lazy="raise")  # noqa: F821
