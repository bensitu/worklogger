"""Localized source references shared by report previews and Markdown delivery."""

from worklogger.infrastructure.i18n import _


def provenance_text(value, *, include_references=True, reference_limit=None):
    if not value.generated_at:
        return _("Source information unavailable for this report.")
    lines = [_("Generated: {time}").format(time=value.generated_at),
             _("Language: {language}").format(language=value.language),
             _("Standard daily hours: {hours:g}").format(hours=value.standard_hours),
             _("Source references: {count}").format(count=len(value.sources)),
             _("Template fingerprint: {digest}").format(digest=value.template_digest or "-")]
    lines.append(_("Sources describe the last generation, not verification of later text edits."))
    labels = {"record": _("Time record"), "note": _("Notes"), "calendar": _("Calendar"), "quick_log": _("Historical items")}
    references = value.sources if include_references else ()
    if reference_limit is not None and len(references) > reference_limit:
        lines.append(_("Showing the first {count} source references.").format(count=reference_limit))
        references = references[:reference_limit]
    for source in references:
        lines.append(f"{labels.get(source.kind, source.kind)} #{source.identifier} | {source.revision if source.revision is not None else '-'} | {source.digest}")
    return "\n".join(lines)
