from .settings_dialog import SettingsDialog
from .work_dialogs import NoteEditorDialog, ReportDialog, ChartDialog, QuickLogDialog
from .template_dialogs import TemplatePickerDialog, CreateTemplateDialog
from .ai_dialogs import AIProgressDialog, AIResultDialog
from .local_model_dialogs import LocalDownloadDialog
from .color_picker_dialog import ColorPickerDialog
from .login_dialog import LoginDialog
from .register_dialog import RegisterDialog
from .change_password_dialog import ChangePasswordDialog
from .reset_password_dialog import ResetPasswordDialog
from .user_management_dialog import UserManagementDialog

__all__ = [
    "SettingsDialog",
    "NoteEditorDialog",
    "ReportDialog",
    "ChartDialog",
    "QuickLogDialog",
    "TemplatePickerDialog",
    "CreateTemplateDialog",
    "AIProgressDialog",
    "AIResultDialog",
    "LocalDownloadDialog",
    "ColorPickerDialog",
    "LoginDialog",
    "RegisterDialog",
    "ChangePasswordDialog",
    "ResetPasswordDialog",
    "UserManagementDialog",
]
