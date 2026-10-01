"""Localized date labels shared by calendar and reporting surfaces."""

from datetime import date

from worklogger.infrastructure.i18n import _


def month_name(day: date) -> str:
    return (
        _("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
        _("July"), _("August"), _("September"), _("October"), _("November"), _("December"),
    )[day.month - 1]


def month_label(day: date) -> str:
    return _("{month} {year}").format(month=month_name(day), year=day.year)


def day_label(day: date) -> str:
    return _("{month} {day}, {year}").format(month=month_name(day), day=day.day, year=day.year)
