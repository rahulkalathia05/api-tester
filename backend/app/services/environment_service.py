"""
Environment management service.

Ownership is always verified through the workspace → user chain before any
mutation.  Secret variable values are never returned to callers; the
read-masked sentinel "***" is used in their place.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment import Environment, EnvironmentVariable
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.workspace_repo import WorkspaceRepository
from app.schemas.environments import (
    BulkUpsertRequest,
    CreateEnvironmentRequest,
    CreateVariableRequest,
    EnvironmentDetail,
    EnvironmentOut,
    PreviewRequest,
    PreviewResponse,
    UpdateEnvironmentRequest,
    UpdateVariableRequest,
    VariableOut,
    _SECRET_SENTINEL,
)
from app.utils.interpolation import interpolate

_404_ENV = HTTPException(status_code=404, detail="Environment not found")
_404_VAR = HTTPException(status_code=404, detail="Variable not found")
_404_WS  = HTTPException(status_code=404, detail="Workspace not found")

_ENV_PATTERN = re.compile(r"\{\{env\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _mask(var: EnvironmentVariable) -> VariableOut:
    return VariableOut(
        id=var.id,
        environment_id=var.environment_id,
        key=var.key,
        value=_SECRET_SENTINEL if var.is_secret else var.value,
        is_secret=var.is_secret,
    )


class EnvironmentService:

    def __init__(self, db: AsyncSession) -> None:
        self._db      = db
        self._ws_repo = WorkspaceRepository(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_env_owned(self, env_id: str, user_id: str) -> Environment:
        row = await self._db.execute(
            select(Environment)
            .join(Workspace, Workspace.id == Environment.workspace_id)
            .where(Environment.id == env_id, Workspace.user_id == user_id)
        )
        env = row.scalar_one_or_none()
        if env is None:
            raise _404_ENV
        return env

    async def _get_var_owned(self, var_id: str, user_id: str) -> EnvironmentVariable:
        row = await self._db.execute(
            select(EnvironmentVariable)
            .join(Environment, Environment.id == EnvironmentVariable.environment_id)
            .join(Workspace,   Workspace.id   == Environment.workspace_id)
            .where(EnvironmentVariable.id == var_id, Workspace.user_id == user_id)
        )
        var = row.scalar_one_or_none()
        if var is None:
            raise _404_VAR
        return var

    async def _var_count(self, env_id: str) -> int:
        from sqlalchemy import func
        r = await self._db.execute(
            select(func.count(EnvironmentVariable.id))
            .where(EnvironmentVariable.environment_id == env_id)
        )
        return r.scalar() or 0

    async def _load_vars(self, env_id: str) -> list[EnvironmentVariable]:
        rows = await self._db.execute(
            select(EnvironmentVariable)
            .where(EnvironmentVariable.environment_id == env_id)
            .order_by(EnvironmentVariable.key)
        )
        return list(rows.scalars().all())

    # ── Environments ──────────────────────────────────────────────────────────

    async def list_environments(self, user: User, workspace_id: str) -> list[EnvironmentOut]:
        if await self._ws_repo.get_owned(workspace_id, user.id) is None:
            raise _404_WS

        rows = await self._db.execute(
            select(Environment)
            .where(Environment.workspace_id == workspace_id)
            .order_by(Environment.is_active.desc(), Environment.created_at)
        )
        envs = list(rows.scalars().all())
        result = []
        for e in envs:
            count = await self._var_count(e.id)
            result.append(EnvironmentOut(
                id=e.id, workspace_id=e.workspace_id,
                name=e.name, is_active=e.is_active,
                created_at=e.created_at, variable_count=count,
            ))
        return result

    async def create_environment(
        self,
        user: User,
        workspace_id: str,
        body: CreateEnvironmentRequest,
    ) -> EnvironmentOut:
        if await self._ws_repo.get_owned(workspace_id, user.id) is None:
            raise _404_WS

        env = Environment(workspace_id=workspace_id, name=body.name, is_active=False)
        self._db.add(env)
        await self._db.flush()
        return EnvironmentOut(
            id=env.id, workspace_id=env.workspace_id,
            name=env.name, is_active=env.is_active,
            created_at=env.created_at, variable_count=0,
        )

    async def get_environment(self, user: User, env_id: str) -> EnvironmentDetail:
        env  = await self._get_env_owned(env_id, user.id)
        vars_ = await self._load_vars(env_id)
        return EnvironmentDetail(
            id=env.id, workspace_id=env.workspace_id,
            name=env.name, is_active=env.is_active,
            created_at=env.created_at,
            variable_count=len(vars_),
            variables=[_mask(v) for v in vars_],
        )

    async def update_environment(
        self,
        user: User,
        env_id: str,
        body: UpdateEnvironmentRequest,
    ) -> EnvironmentOut:
        env = await self._get_env_owned(env_id, user.id)
        env.name = body.name
        count = await self._var_count(env_id)
        return EnvironmentOut(
            id=env.id, workspace_id=env.workspace_id,
            name=env.name, is_active=env.is_active,
            created_at=env.created_at, variable_count=count,
        )

    async def delete_environment(self, user: User, env_id: str) -> None:
        env = await self._get_env_owned(env_id, user.id)
        await self._db.delete(env)
        await self._db.flush()

    async def activate_environment(self, user: User, env_id: str) -> EnvironmentOut:
        """
        Set this environment as active and deactivate all others in the workspace.
        Only one environment per workspace can be active at a time.
        """
        env = await self._get_env_owned(env_id, user.id)

        # Deactivate all siblings
        siblings = await self._db.execute(
            select(Environment).where(
                Environment.workspace_id == env.workspace_id,
                Environment.id != env_id,
                Environment.is_active.is_(True),
            )
        )
        for sib in siblings.scalars().all():
            sib.is_active = False

        env.is_active = True
        await self._db.flush()

        count = await self._var_count(env_id)
        return EnvironmentOut(
            id=env.id, workspace_id=env.workspace_id,
            name=env.name, is_active=env.is_active,
            created_at=env.created_at, variable_count=count,
        )

    async def deactivate_environment(self, user: User, env_id: str) -> EnvironmentOut:
        env = await self._get_env_owned(env_id, user.id)
        env.is_active = False
        await self._db.flush()
        count = await self._var_count(env_id)
        return EnvironmentOut(
            id=env.id, workspace_id=env.workspace_id,
            name=env.name, is_active=env.is_active,
            created_at=env.created_at, variable_count=count,
        )

    # ── Variables ─────────────────────────────────────────────────────────────

    async def list_variables(self, user: User, env_id: str) -> list[VariableOut]:
        await self._get_env_owned(env_id, user.id)
        vars_ = await self._load_vars(env_id)
        return [_mask(v) for v in vars_]

    async def create_variable(
        self,
        user: User,
        env_id: str,
        body: CreateVariableRequest,
    ) -> VariableOut:
        await self._get_env_owned(env_id, user.id)

        # Enforce unique key within this environment
        existing = await self._db.execute(
            select(EnvironmentVariable).where(
                EnvironmentVariable.environment_id == env_id,
                EnvironmentVariable.key == body.key,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Variable '{body.key}' already exists in this environment",
            )

        var = EnvironmentVariable(
            environment_id=env_id,
            key=body.key,
            value=body.value,
            is_secret=body.is_secret,
        )
        self._db.add(var)
        await self._db.flush()
        return _mask(var)

    async def bulk_upsert_variables(
        self,
        user: User,
        env_id: str,
        body: BulkUpsertRequest,
    ) -> list[VariableOut]:
        """
        Replace all variables for an environment.

        Secret variable items whose value equals "***" (the read mask) are
        preserved from the database — the caller didn't know the real value,
        so we don't overwrite it.  Any other value (including a new string)
        will be stored.
        """
        await self._get_env_owned(env_id, user.id)

        # Load existing secrets so we can preserve them if value is sentinel
        existing = await self._load_vars(env_id)
        secret_map = {v.key: v.value for v in existing if v.is_secret}

        # Delete all existing variables
        for var in existing:
            await self._db.delete(var)
        await self._db.flush()

        # Re-insert from the request
        new_vars: list[EnvironmentVariable] = []
        for item in body.variables:
            value = item.value
            if item.is_secret and value == _SECRET_SENTINEL:
                # Preserve the stored secret value if the caller didn't change it
                value = secret_map.get(item.key, "")

            var = EnvironmentVariable(
                environment_id=env_id,
                key=item.key,
                value=value,
                is_secret=item.is_secret,
            )
            self._db.add(var)
            new_vars.append(var)

        # Flush assigns the DB-generated IDs; mask() must run after
        await self._db.flush()
        return [_mask(v) for v in new_vars]

    async def update_variable(
        self,
        user: User,
        var_id: str,
        body: UpdateVariableRequest,
    ) -> VariableOut:
        var = await self._get_var_owned(var_id, user.id)
        if body.key is not None:
            var.key = body.key
        if body.value is not None:
            var.value = body.value
        if body.is_secret is not None:
            var.is_secret = body.is_secret
        await self._db.flush()
        return _mask(var)

    async def delete_variable(self, user: User, var_id: str) -> None:
        var = await self._get_var_owned(var_id, user.id)
        await self._db.delete(var)
        await self._db.flush()

    # ── Preview ───────────────────────────────────────────────────────────────

    async def preview_interpolation(
        self,
        user: User,
        env_id: str,
        body: PreviewRequest,
    ) -> PreviewResponse:
        """
        Substitute {{env.KEY}} placeholders in the template using the
        environment's variables and report which were resolved / unresolved.
        """
        await self._get_env_owned(env_id, user.id)

        vars_ = await self._load_vars(env_id)
        var_map = {v.key: v.value for v in vars_}

        # Keys referenced in the template
        all_keys = set(_ENV_PATTERN.findall(body.template))

        result = interpolate(body.template, var_map)

        resolved   = [k for k in all_keys if k in var_map]
        unresolved = [k for k in all_keys if k not in var_map]

        return PreviewResponse(
            result=result,
            resolved_keys=sorted(resolved),
            unresolved_keys=sorted(unresolved),
        )
