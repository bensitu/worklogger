"""Safe infrastructure boundaries for application operations."""

from functools import wraps

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


def storage_boundary(code: str):
    def decorate(operation):
        @wraps(operation)
        def guarded(*args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except Exception:
                return Result.failure(InfrastructureError(code, code))
        return guarded
    return decorate
