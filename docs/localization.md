# Localization

## Catalogs

Application strings use gettext through `worklogger.infrastructure.i18n`.
Supported catalogs are `en_US`, `ja_JP`, `ko_KR`, `zh_CN`, and `zh_TW` under
`worklogger/locales/<language>/LC_MESSAGES/`.

- `messages.pot`: extracted message template, tracked in Git.
- `messages.po`: translated source catalog, tracked in Git.
- `messages.mo`: compiled runtime catalog, generated and excluded from Git.

`_()` translates a single message and `ngettext()` selects a plural form. Use a
literal English message as the extraction key. Format named values after
translation rather than constructing a translated message dynamically.

Error codes are diagnostic identifiers, not translation keys. The presentation
helpers in `worklogger/presentation/errors.py` map them to literal English gettext
messages. Unknown errors use a neutral fallback without exposing exception text.
Validation previews use the same messages without logging every input change.

```python
from worklogger.infrastructure.i18n import _

message = _("Last backup: {time}").format(time="2026-05-21 09:00")
```

## Updating Strings

Run the scripts directly from the repository root:

```sh
python scripts/i18n/i18n_extract.py
python scripts/i18n/i18n_sync.py
```

Translate new entries in all supported PO files, preserving named formatting
fields, plural forms, and any Qt position parameters such as `%1`. Then:

```sh
python scripts/i18n/i18n_compile.py
python scripts/i18n/i18n_check.py
python -m unittest tests.i18n.test_gettext_foundation -v
```

The compiler is provided by the repository; GNU gettext executables are not needed
for these commands. Synchronization preserves existing translations but does not
translate new messages automatically. Empty or missing translations fall back to
the source string at runtime.

## Language Selection

Pre-login preference handling is in `infrastructure/language_preferences.py`.
System language matching uses Qt locale information, including Chinese region and
script variants. The login preference is separate from the account language in
SQLite. See [resolution order](configuration.md).

The language dropdown always displays the language's own name, independently of
the current interface language. Changing the preference does not rebuild all
existing widgets: restart or log in again to apply the translated interface.

Calendar labels and period descriptions use presentation date helpers. Holiday
names are supplied by the holiday provider and are not translated by the
application's gettext catalogs.

## Qt Controls

Application translations do not automatically translate Qt's built-in dialogs.
The color picker uses a scoped `QTranslator` adapter whose values come from the
same gettext catalogs, and selects the Qt-rendered dialog so the OS language does
not override the chosen interface language. The adapter is removed when the modal
dialog closes. It does not introduce a second translation catalog format.

When upgrading Qt, verify color-field labels, standard buttons, and screen-color
selection instructions. Their source texts and translation contexts are defined
by Qt and may need corresponding adapter changes.

## Rendering

Bundled Noto fonts are installed before constructing the interface. Verify text
widths and heights in every language, including input fields, dropdowns, buttons,
calendar holidays, and dialogs. Do not assume that English measurements cover
Japanese, Korean, or Chinese. See [visual tests](testing.md).
