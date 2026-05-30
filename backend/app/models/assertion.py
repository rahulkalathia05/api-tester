import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Assertion(Base):
    """
    Expected condition for an API request.

    type     : status_code | response_time | json_path | header | body_contains
    operator : eq | ne | gt | lt | gte | lte | contains | not_contains | exists | matches
    path     : JSONPath expression (only for json_path type), e.g. $.data.id
    """
    __tablename__ = "assertions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    operator: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_value: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text)   # JSONPath
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    request: Mapped["ApiRequest"] = relationship(back_populates="assertions", lazy="raise")  # noqa: F821
