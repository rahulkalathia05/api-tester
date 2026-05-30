import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="workspaces", lazy="raise")  # noqa: F821
    collections: Mapped[list["Collection"]] = relationship(  # noqa: F821
        back_populates="workspace", cascade="all, delete-orphan", lazy="raise"
    )
    environments: Mapped[list["Environment"]] = relationship(  # noqa: F821
        back_populates="workspace", cascade="all, delete-orphan", lazy="raise"
    )
    test_runs: Mapped[list["TestRun"]] = relationship(  # noqa: F821
        back_populates="workspace", cascade="all, delete-orphan", lazy="raise"
    )
