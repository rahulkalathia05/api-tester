from sqlalchemy import exists, select
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        # Email is already normalised to lowercase by the schema; the .lower()
        # call here is a safety net for any code path that bypasses the schema.
        result = await self._session.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        # SELECT EXISTS(...) transfers a single boolean from the DB instead of
        # fetching and deserialising a full User row just to discard it.
        result = await self._session.execute(
            select(exists().where(User.email == email.lower()))
        )
        return bool(result.scalar())
