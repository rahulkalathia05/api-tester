import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ApiRequest(Base):
    """
    A single HTTP request stored in a collection.

    Named ApiRequest (not Request) to avoid shadowing the built-in and
    the httpx.Request type throughout the codebase.
    """
    __tablename__ = "api_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id: Mapped[str] = mapped_column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)      # GET POST PUT PATCH DELETE
    url: Mapped[str] = mapped_column(Text, nullable=False)               # supports {{env.KEY}}
    headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    body_type: Mapped[str] = mapped_column(String(20), default="json", nullable=False)  # json|form|raw|none
    auth_type: Mapped[str] = mapped_column(String(20), default="none", nullable=False)  # none|bearer|basic|api_key
    auth_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30_000, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    collection: Mapped["Collection"] = relationship(back_populates="requests", lazy="raise")  # noqa: F821
    assertions: Mapped[list["Assertion"]] = relationship(  # noqa: F821
        back_populates="request", cascade="all, delete-orphan", lazy="raise"
    )
