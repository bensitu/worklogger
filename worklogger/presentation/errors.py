"""Presentation helpers for user-visible error messages."""

from __future__ import annotations

import logging

from worklogger.config.constants import PASSWORD_MIN_LENGTH
from worklogger.domain.shared.errors import AppError, CancellationError
from worklogger.infrastructure.i18n import _

LOGGER = logging.getLogger(__name__)


def display_error_message(error: AppError | None) -> str:
    """Return a translated message safe for direct UI display."""

    if isinstance(error, CancellationError):
        return _("Operation cancelled.")
    if error is not None and logging.getLogger().handlers:
        LOGGER.error("app_error_displayed", extra={"error_code": error.code})
    return display_error_code(error.code) if error is not None else _("Unknown error")


def display_error_code(code: str) -> str:
    """Translate known error codes without displaying raw exception text or logging previews."""

    match code:
        case "local_runtime_context_invalid":
            return _("Runtime context must be a whole number of at least 512 tokens.")
        case "local_model_context_limit_invalid":
            return _("The selected model's context limit is too small for text processing.")
        case "display_name_invalid":
            return _("Use a single-line display name without control characters.")
        case "display_name_too_long":
            return _("Display names must not exceed 80 characters.")
        case "user_profile_conflict":
            return _("Your display name changed elsewhere. Cancel to reload it before saving; your input has been retained.")
        case "user_profile_save_failed":
            return _("Unable to save your display name. Your input has been retained.")
        case "user_profile_load_failed":
            return _("Unable to load the user profile. Please try again.")
        case "fixed_break_hours_invalid":
            return _("Break duration must be greater than zero and no more than four hours.")
        case "duplicate_date":
            return _("The file contains conflicting records for the same date.")
        case "description_too_long":
            return _("Content must not exceed 16,000 characters.")
        case "template_content_too_long":
            return _("Template content must not exceed 1 MiB.")
        case "worklog_entry_overlap" | "fixed_break_active":
            return _("These times overlap another record or the active timer. Choose a different period.")
        case "worklog_entry_conflict" | "time_entry_timer_conflict":
            return _("This record changed elsewhere. Reload it before saving. Your changes have been retained.")
        case "time_entry_content_too_long":
            return _("Content must not exceed 16,000 characters.")
        case "worklog_summary_not_editable":
            return _("Select an individual time record to edit this day.")
        case "auto_record_pending_save":
            return _("Save the completed automatic record before starting another.")
        case "auto_record_restore_failed" | "auto_record_state_save_failed":
            return _("Unable to update automatic recording state. Your saved data has been retained.")
        case "note_conflict":
            return _("This note was changed in another editor. Reload it before saving. Your changes have been retained.")
        case "note_save_failed":
            return _("Unable to save the note. Your changes have been retained.")
        case "note_load_failed":
            return _("Unable to load daily notes. Your saved data has been retained.")
        case "csv_file_too_large":
            return _("The CSV file exceeds the supported size or row limit.")
        case "csv_import_conflict":
            return _("Some dates already have records. Review the import and confirm replacement.")
        case "ics_recurrence_unbounded":
            return _("Recurring events must have an end date or occurrence count.")
        case "report_not_found":
            return _("The saved report is no longer available. Reload the reports and try again.")
        case "report_save_failed":
            return _("Unable to save the report. Your changes have been retained.")
        case "report_delete_failed":
            return _("Unable to delete the report. Your saved data has been retained.")
        case "report_conflict":
            return _("This report changed elsewhere. Reload the history before deleting it.")
        case "desktop_runtime_failed" | "auth_state_failed":
            return _("Unable to start WorkLogger. Check the application log for details.")
        case "runtime_user_required" | "runtime_user_missing" | "auth_required":
            return _("Please sign in to continue.")
        case "invalid_credentials":
            return _("The ID or password is incorrect.")
        case "username_exists":
            return _("This ID is already in use. Choose a different ID.")
        case "username_required" | "username_must_be_string":
            return _("Enter your ID.")
        case "password_required" | "current_password_required" | "new_password_required":
            return _("Enter your password.")
        case "password_too_short":
            return _("The password must contain at least {length} characters.").format(length=PASSWORD_MIN_LENGTH)
        case "registration_password_mismatch" | "password_change_mismatch" | "password_reset_mismatch" | "managed_user_password_mismatch":
            return _("The passwords do not match.")
        case "invalid_recovery_key" | "recovery_key_required":
            return _("Enter a valid recovery key.")
        case "invalid_remember_token" | "remember_token_required":
            return _("Your saved sign-in is invalid or expired. Please sign in again.")
        case "remember_session_save_failed" | "remember_session_load_failed" | "remember_session_clear_failed" | "remember_login_unavailable":
            return _("Unable to update saved sign-in information.")
        case "admin_required":
            return _("Administrator permission is required.")
        case "cannot_delete_self" | "cannot_delete_last_admin":
            return _("You cannot delete your own account or the last administrator.")
        case "user_not_found" | "identity_user_missing":
            return _("The user account is no longer available.")
        case "credential_storage_unavailable":
            return _("Secure credential storage is unavailable.")
        case "secret_authentication_failed" | "secret_key_missing" | "secret_key_invalid" | "secret_ciphertext_invalid" | "credential_reentry_required":
            return _("The stored credential cannot be decrypted on this device. Enter it again; existing work records are unaffected.")
        case "database_corrupt":
            return _("The database could not be read. The original files have been retained. Restore a verified backup using the database recovery instructions.")
        case "local_inference_dependency_missing":
            return _("Install the native inference dependency from requirements-ai.txt, then restart WorkLogger.")
        case "local_model_not_selected":
            return _("Select a verified model in Manage models.")
        case "ai_assist_disabled":
            return _("Enable AI Assist to use text processing.")
        case "ai_service_disabled":
            return _("AI Assist is disabled for this installation.")
        case "local_model_disabled":
            return _("Enable the local model to use text processing.")
        case "local_model_load_failed":
            return _("Unable to load the selected model. Check available memory or choose a smaller model.")
        case "local_inference_timeout":
            return _("Local text processing timed out. Try shorter content or a smaller model.")
        case "local_inference_context_limit":
            return _("This text exceeds the selected model's context limit. Shorten it and try again.")
        case "avatar_image_invalid":
            return _("Choose a valid PNG, JPEG, WebP, or BMP image.")
        case "avatar_image_too_large":
            return _("Choose an image smaller than 10 MB and 20 million pixels.")
        case "work_type_invalid":
            return _("Enter a name of up to 80 characters and select an accounting category.")
        case "work_type_name_exists":
            return _("A work type with this name already exists.")
        case "work_type_unavailable" | "work_type_conflict":
            return _("This work type changed or is no longer available. Reload the types and try again.")
        case "work_types_load_failed" | "work_types_save_failed":
            return _("Unable to update work types. Your records have not changed.")
        case "invalid_proxy_port":
            return _("Enter a port between 0 and 65535.")
        case "time_range_invalid" | "time_range_incomplete" | "quick_log_time_range_invalid" | "start_time_required":
            return _("Enter valid start and end times in HH:mm format.")
        case "break_hours_negative" | "break_hours_too_long" | "auto_record_break_minutes_invalid":
            return _("Break time must be nonnegative and shorter than the work period.")
        case "date_range_invalid" | "date_required" | "month_required":
            return _("Select a valid date or date range.")
        case "report_not_loaded":
            return _("The report has not loaded. Reload it before continuing.")
        case "report_export_empty":
            return _("No saved daily reports exist in the selected date range.")
        case "description_required" | "report_content_required" | "rewrite_content_required" | "template_content_required" | "ai_chat_message_required":
            return _("Enter content before continuing.")
        case "quick_log_not_selected":
            return _("Select a quick log first.")
        case "quick_log_not_found":
            return _("The quick log is no longer available. Reload the records and try again.")
        case "quick_log_save_failed" | "quick_log_delete_failed":
            return _("Unable to update the quick log. Your changes have been retained.")
        case "auto_record_already_active" | "auto_record_break_already_active":
            return _("Recording or a break is already active.")
        case "auto_record_not_started" | "auto_record_break_not_active":
            return _("Start recording or a break before continuing.")
        case "backup_same_path":
            return _("Choose a backup destination different from the active database.")
        case "backup_failed" | "backup_memory_database":
            return _("Unable to back up the database. Check the destination and available disk space.")
        case "restore_failed" | "restore_memory_database" | "restore_source_missing" | "restore_validation_failed":
            return _("Unable to restore the database. Select a valid SQLite backup.")
        case "csv_import_failed" | "ics_import_failed" | "ics_read_failed" | "ics_file_too_large" | "csv_import_unavailable" | "ics_import_unavailable":
            return _("Unable to import the file. Check its format and contents.")
        case "csv_export_failed" | "ics_export_failed" | "markdown_export_failed" | "analytics_csv_export_failed" | "analytics_pdf_export_failed":
            return _("Unable to export the file. Check the destination and write permissions.")
        case "update_check_failed":
            return _("Unable to check for updates. Check your network connection and try again.")
        case "settings_save_failed":
            return _("Unable to save settings. Please try again.")
        case "holiday_region_invalid":
            return _("Select a supported holiday country and state or province.")
        case "worklog_save_failed":
            return _("Unable to save the work log. Your changes have been retained.")
        case "settings_load_failed" | "note_load_failed" | "worklog_load_failed" | "worklog_export_load_failed" | "calendar_load_failed" | "holiday_load_failed" | "analytics_load_failed" | "stats_load_failed" | "user_list_failed":
            return _("Unable to load data. Please try again.")
        case "ai_chat_not_configured" | "ai_rewrite_not_configured" | "ai_secondary_not_configured" | "ai_api_key_required" | "ai_configuration_invalid":
            return _("AI Assist is not configured.")
        case "ai_chat_empty" | "ai_rewrite_empty" | "local_model_empty_response":
            return _("The model returned no content. Please try again.")
        case "ai_chat_failed" | "ai_rewrite_failed" | "ai_request_failed" | "ai_context_failed" | "ai_context_settings_failed" | "local_model_generation_failed":
            return _("Unable to complete the AI request. Check your model settings and try again.")
        case "ai_context_too_large":
            return _("The selected context is too large. Choose a shorter period or exclude optional content.")
        case "local_model_missing" | "local_model_file_missing" | "local_model_not_configured":
            return _("Local model unavailable. Download, import and select a verified model.")
        case "local_model_empty" | "local_model_file_empty" | "local_model_file_must_be_gguf" | "local_model_hash_mismatch" | "local_model_hash_required" | "local_model_verify_failed":
            return _("Model verification failed. Import or download a valid GGUF model.")
        case "local_model_id_required":
            return _("Select a model first.")
        case "local_model_permission_denied":
            return _("Unable to read the model file. Check its access permissions.")
        case "local_model_download_failed" | "local_model_download_url_missing" | "local_model_import_failed":
            return _("Unable to obtain the model. Check the source file or download connection.")
        case "local_model_used_by_another_user":
            return _("This model is in use by another user and cannot be deleted.")
        case "identity_auth_failed" | "identity_login_failed" | "identity_nonce_mismatch" | "identity_subject_missing" | "identity_token_invalid":
            return _("Unable to sign in with this provider. Please try again.")
        case "identity_already_linked":
            return _("This identity is already linked to an account.")
        case "identity_last_login_method":
            return _("Add another sign-in method before unlinking this identity.")
        case _:
            return _("The operation could not be completed. Please try again.")
