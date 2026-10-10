"""Account-scoped profile reads and optimistic display-name updates."""

from worklogger.domain.auth.models import User
from worklogger.domain.auth.profile import normalize_display_name
from worklogger.domain.auth.repositories import UserProfileRepository
from worklogger.domain.shared.errors import ConflictError, InfrastructureError, NotFoundError, ValidationError
from worklogger.domain.shared.result import Result


class UserProfileService:
    def __init__(self, *, user_id: int, repository: UserProfileRepository):
        self._user_id = user_id
        self._repository = repository

    def load(self) -> Result[User]:
        try:
            user = self._repository.get_by_id(self._user_id)
        except Exception:
            return Result.failure(InfrastructureError("user_profile_load_failed", "user_profile_load_failed"))
        if user is None or user.id != self._user_id:
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        return Result.success(user)

    def save_display_name(self, value: str, *, expected_display_name: str) -> Result[User]:
        try:
            name = normalize_display_name(value)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        try:
            return Result.success(self._repository.set_display_name(
                self._user_id, name, expected_display_name=expected_display_name))
        except ValueError as exc:
            if str(exc) == "user_profile_conflict":
                return Result.failure(ConflictError("user_profile_conflict", "user_profile_conflict"))
            if str(exc) == "user_not_found":
                return Result.failure(NotFoundError("user_not_found", "user_not_found"))
            return Result.failure(ValidationError("display_name_invalid", "display_name_invalid"))
        except Exception:
            return Result.failure(InfrastructureError("user_profile_save_failed", "user_profile_save_failed"))


def profile_display_name(repository: UserProfileRepository | None, user_id: int) -> str:
    if repository is None:
        return ""
    user = repository.get_by_id(user_id)
    if user is None or user.id != user_id:
        raise ValueError("user_not_found")
    return user.effective_display_name
