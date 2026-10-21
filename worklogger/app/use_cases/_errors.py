"""Safe infrastructure boundaries for application operations."""

from functools import wraps
import logging

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


def infrastructure_failure(code: str, error: Exception, *, logger_name: str) -> InfrastructureError:
    if isinstance(error, ValueError) and str(error) == "stored_work_logs_invalid":
        code = "stored_work_logs_invalid"
    logging.getLogger(logger_name).error("%s: %s", code, type(error).__name__)
    return InfrastructureError(code, code, {"reason": type(error).__name__})


def storage_boundary(code: str):
    def decorate(operation):
        @wraps(operation)
        def guarded(*args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except Exception as error:
                return Result.failure(infrastructure_failure(code, error, logger_name=operation.__module__))
        return guarded
    return decorate
