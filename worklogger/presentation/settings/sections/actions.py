"""Explicit callbacks shared by settings sections."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class SectionActions:
    change_avatar_requested: Callable
    reset_avatar_requested: Callable
    backup_requested: Callable
    change_password_requested: Callable
    choose_custom_color: Callable
    confirm_logout: Callable
    export_csv_requested: Callable
    export_ics_requested: Callable
    holiday_country_changed: Callable
    holiday_subdivision_changed: Callable
    import_csv_requested: Callable
    import_ics_requested: Callable
    language_changed: Callable
    manage_identities_requested: Callable
    manage_local_models_requested: Callable
    manage_users_requested: Callable
    manage_work_types_requested: Callable
    mode_changed: Callable
    residency_key: str | None
    restore_requested: Callable
    save_external_api_key: Callable
    set_bool: Callable[[str, bool], None]
    set_number: Callable[[str, float], None]
    set_text: Callable[[str, str], None]
    theme_changed: Callable
    toggle_proxy_password: Callable
    update_check_requested: Callable
