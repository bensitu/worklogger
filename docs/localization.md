# Localization

## Catalogs

User-visible strings use gettext through `worklogger.infrastructure.i18n`.
Supported catalogs are `en_US`, `ja_JP`, `ko_KR`, `zh_CN`, and `zh_TW`.

- Track `messages.pot` and the translated `messages.po` source files.
- Generate `messages.mo` for runtime use; do not commit compiled catalogs.
- Use literal English message keys and named placeholders.
- Use `ngettext()` for plural selection.

Format after translation:

```python
from worklogger.infrastructure.i18n import _

message = _("Last backup: {time}").format(time="2030-01-15 09:00")
```

Presentation maps error codes to translated messages. Do not expose raw exception
payloads or use dynamically constructed extraction keys.

## Updating Strings

```sh
python scripts/i18n/i18n_extract.py
python scripts/i18n/i18n_sync.py
```

Translate new entries in all supported PO files. Preserve named placeholders,
plural forms, and Qt parameters such as `%1`. Then:

```sh
python scripts/i18n/i18n_compile.py
python scripts/i18n/i18n_check.py
python -m unittest tests.i18n.test_gettext_foundation -v
```

The repository compiler does not need a separate GNU gettext installation.
Synchronization preserves translations but does not translate new messages.
Missing runtime translations fall back to the English source.

## Activation and Qt

Startup and language changes explicitly activate catalogs. Account language and
device login language are separate; see [configuration](configuration.md).
The dropdown displays each language's own name.

The color picker uses a scoped Qt translator backed by the same catalogs.
Remove it when the dialog closes. Qt's built-in dialog strings and platform-native
dialogs need their own target checks.

Use bundled fonts and localized date helpers. Holiday names come from their data
provider. Check long labels, input fields, menus, and error text in representative
languages and themes. See [testing](testing.md).
