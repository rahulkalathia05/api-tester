from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.api_request import ApiRequest
from app.models.assertion import Assertion
from app.models.collection import Collection
from app.models.workspace import Workspace
from app.repositories.base import BaseRepository


class CollectionRepository(BaseRepository[Collection]):
    model = Collection

    # ── Ownership-aware fetches ────────────────────────────────────────────────

    async def get_owned(self, collection_id: str, user_id: str) -> Collection | None:
        """Return the collection only if its workspace belongs to user_id."""
        result = await self._session.execute(
            select(Collection)
            .join(Workspace, Workspace.id == Collection.workspace_id)
            .where(
                Collection.id == collection_id,
                Workspace.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_detail(self, collection_id: str, user_id: str) -> Collection | None:
        """Like get_owned but eagerly loads requests (without assertions)."""
        result = await self._session.execute(
            select(Collection)
            .join(Workspace, Workspace.id == Collection.workspace_id)
            .where(
                Collection.id == collection_id,
                Workspace.user_id == user_id,
            )
            .options(selectinload(Collection.requests))
        )
        return result.scalar_one_or_none()

    # ── Paginated list with optional name filter ──────────────────────────────

    async def list_by_workspace(
        self,
        workspace_id: str,
        user_id: str,
        *,
        page: int,
        page_size: int,
        name: str | None,
    ) -> tuple[list[Collection], int]:
        """
        Return (items, total) for the given page.
        Ownership is checked via the workspace.user_id join.
        """
        base = (
            select(Collection)
            .join(Workspace, Workspace.id == Collection.workspace_id)
            .where(
                Collection.workspace_id == workspace_id,
                Workspace.user_id == user_id,
            )
        )

        if name:
            # Case-insensitive substring match — works on PostgreSQL and SQLite.
            base = base.where(Collection.name.ilike(f"%{name}%"))

        count_q = select(func.count()).select_from(base.subquery())
        total: int = (await self._session.execute(count_q)).scalar() or 0

        rows = await self._session.execute(
            base.order_by(Collection.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.scalars().all()), total

    async def count_requests(self, collection_id: str) -> int:
        result = await self._session.execute(
            select(func.count(ApiRequest.id)).where(
                ApiRequest.collection_id == collection_id
            )
        )
        return result.scalar() or 0


class ApiRequestRepository(BaseRepository[ApiRequest]):
    model = ApiRequest

    # ── Ownership-aware fetches ────────────────────────────────────────────────

    async def get_owned(self, request_id: str, user_id: str) -> ApiRequest | None:
        """Return the request only if its workspace belongs to user_id."""
        result = await self._session.execute(
            select(ApiRequest)
            .join(Collection, Collection.id == ApiRequest.collection_id)
            .join(Workspace, Workspace.id == Collection.workspace_id)
            .where(
                ApiRequest.id == request_id,
                Workspace.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_detail(self, request_id: str, user_id: str) -> ApiRequest | None:
        """Like get_owned but eagerly loads assertions."""
        result = await self._session.execute(
            select(ApiRequest)
            .join(Collection, Collection.id == ApiRequest.collection_id)
            .join(Workspace, Workspace.id == Collection.workspace_id)
            .where(
                ApiRequest.id == request_id,
                Workspace.user_id == user_id,
            )
            .options(selectinload(ApiRequest.assertions))
        )
        return result.scalar_one_or_none()

    # ── Collection-scoped queries ──────────────────────────────────────────────

    async def list_by_collection(
        self, collection_id: str, user_id: str
    ) -> list[ApiRequest]:
        """All requests in a collection the user owns, ordered by order_index."""
        result = await self._session.execute(
            select(ApiRequest)
            .join(Collection, Collection.id == ApiRequest.collection_id)
            .join(Workspace, Workspace.id == Collection.workspace_id)
            .where(
                ApiRequest.collection_id == collection_id,
                Workspace.user_id == user_id,
            )
            .order_by(ApiRequest.order_index, ApiRequest.created_at)
        )
        return list(result.scalars().all())

    async def max_order_index(self, collection_id: str) -> int:
        """Return the current highest order_index so new requests append to the end."""
        result = await self._session.execute(
            select(func.max(ApiRequest.order_index)).where(
                ApiRequest.collection_id == collection_id
            )
        )
        return result.scalar() or 0
