"""Safe error translation shared by application and presentation operations."""

from functools import wraps
import logging
import re

from worklogger.domain.shared.errors import AppError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


def infrastructure_failure(code: str, error: Exception, *, logger_name: str) -> InfrastructureError:
    if isinstance(error, ValueError) and re.fullmatch(r"stored_[a-z0-9_]+_invalid", str(error)):
        code = str(error)
    logging.getLogger(logger_name).error("%s: %s", code, type(error).__name__)
    return InfrastructureError(code, code, {"reason": type(error).__name__})


def application_failure(code: str, error: Exception, *, logger_name: str) -> AppError:
    if isinstance(error, ValueError):
        reason = str(error)
        if not reason.startswith("stored_") and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", reason):
            return ValidationError(reason, reason)
    return infrastructure_failure(code, error, logger_name=logger_name)


def storage_boundary(code: str):
    def decorate(operation):
        @wraps(operation)
        def guarded(*args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except Exception as error:
                return Result.failure(application_failure(code, error, logger_name=operation.__module__))
        return guarded
    return decorate
