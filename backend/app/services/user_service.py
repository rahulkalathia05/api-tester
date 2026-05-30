from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, UpdateProfileRequest, UserOut


class UserService:
    """
    User profile and credential operations.

    These methods only touch the database — they never need a Redis client,
    so separating them from AuthService keeps each class's dependencies honest.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def update_profile(self, user: User, body: UpdateProfileRequest) -> UserOut:
        if body.name is not None:
            user.name = body.name
        return UserOut.model_validate(user)

    async def change_password(self, user: User, body: ChangePasswordRequest) -> None:
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )
        user.password_hash = hash_password(body.new_password)
