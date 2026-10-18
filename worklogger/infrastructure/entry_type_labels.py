"""Localized activity labels shared by desktop views and exported documents."""

from worklogger.app import entry_labels
from worklogger.domain.worklog.models import EntryType, CustomEntryType, WorkModeValue
from worklogger.infrastructure.i18n import _


def entry_type_label(entry_type: str | EntryType | CustomEntryType) -> str:
    return entry_labels.entry_type_label(entry_type, _)


def work_mode_label(work_mode: WorkModeValue | str | None) -> str:
    return entry_labels.work_mode_label(work_mode, _)


def classification_label(entry_type: EntryType | CustomEntryType, work_mode: WorkModeValue | None = None) -> str:
    return entry_labels.classification_label(entry_type, work_mode, _)
