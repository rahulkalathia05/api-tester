# Import every model so SQLAlchemy's mapper registry is populated
# before Alembic autogenerate runs or Base.metadata.create_all() is called.
from app.models.user import User
from app.models.workspace import Workspace
from app.models.environment import Environment, EnvironmentVariable
from app.models.collection import Collection
from app.models.api_request import ApiRequest
from app.models.assertion import Assertion
from app.models.test_run import TestRun
from app.models.test_result import TestResult
from app.models.assertion_result import AssertionResult
from app.models.ai_analysis import AiAnalysis
from app.models.scheduled_run import ScheduledRun

__all__ = [
    "User",
    "Workspace",
    "Environment",
    "EnvironmentVariable",
    "Collection",
    "ApiRequest",
    "Assertion",
    "TestRun",
    "TestResult",
    "AssertionResult",
    "AiAnalysis",
    "ScheduledRun",
]
