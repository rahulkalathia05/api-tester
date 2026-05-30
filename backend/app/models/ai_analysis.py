import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AiAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    test_result_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    analysis: Mapped[str] = mapped_column(Text, nullable=False)              # markdown diagnosis
    suggestions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{title, description, code?}]
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    test_result: Mapped["TestResult"] = relationship(back_populates="ai_analysis", lazy="raise")  # noqa: F821
