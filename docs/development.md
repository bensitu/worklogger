# Development

## Setup

Use Python 3.11 through 3.14 and a virtual environment. Run from the repository checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/i18n/i18n_compile.py
.\.venv\Scripts\python.exe -m worklogger.main
```

On macOS/Linux, use `.venv/bin/python`. Activation is optional.
On Debian/Ubuntu desktops, install the Qt runtime libraries used by CI if they
are not already available:

```sh
sudo apt-get install libegl1 libgl1 libopengl0 libxkbcommon-x11-0 libdbus-1-3 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xinerama0
```

Other distributions use different package names. For headless checks, set
`QT_QPA_PLATFORM=offscreen`; leave it unset when launching the interactive app.
For packaging, install `requirements-build.txt`, then run
`python scripts/install_native_dependencies.py`. Every distribution includes
the pinned native inference backend and its dependencies. Source development
can omit the backend when local inference is not used.
Install `requirements-dev.txt` for contributor lint tooling; it is not a runtime
or release-build dependency.

The runtime, native inference, and build lists have separate responsibilities.
Generated JSON locks identify target environments, input fingerprints,
packages, and wheel hashes; companion TXT files install those exact wheels.
Do not merge them into normal runtime dependencies. The approved native artifacts
are listed separately in `requirements/native-artifacts.json`.
See [packaging](packaging.md).

## Code Conventions

Read [architecture](architecture.md) and [contributing](../CONTRIBUTING.md).
Use explicit dependencies, immutable commands/queries, repository contracts,
`Result`, view models, controllers, and existing Qt signals.

Keep calculations out of widgets and storage algorithms out of composition.
Do not introduce speculative abstractions or duplicate established helpers.
Use descriptive English identifiers/comments and standard Python naming.
Describe responsibilities and behavior with neutral, professional terminology.
Remove unused scaffolding rather than preserving it for an unspecified feature.

Keep long operations off the UI thread. Honor cancellation, ownership, optimistic
updates, and disposal. Treat error codes as stable diagnostic identifiers.
Schedule modal workflow dialogs for deletion when their execution ends, including
when loading fails. Keep successful routine actions nonmodal and show their status
inline; reserve message boxes for errors or decisions requiring user input.
Use the shared application error boundary for unexpected storage failures. Log a
stable error code and exception type, not exception messages or user content.
Repository construction must not perform database maintenance. Invoke cleanup
explicitly from composition, and keep optional retention failures separate from
authentication and validation failures.

## Interface Conventions

Use shared theme tokens, controls, fonts, and Lucide icons. Apply QSS at the
application boundary, not on individual widgets.

Shared rules live in responsibility-specific fragments under
`presentation/theme/qss`. `stylesheets.py` defines their cascade order: application
surfaces and text roles, shared controls, component variants, disabled states,
then background overrides. Navigation, item views, menus, tabs, and authentication
each have a dedicated fragment. `selection_controls.qss` owns checkboxes, radio
indicators, and sliders; `scrollbars.qss` owns scroll tracks and handles.
`tool_buttons.qss` consolidates embedded actions, icon sizing, and export indicators
across pages. `popups.qss` owns popup surfaces and menus;
`date_controls.qss` owns calendar navigation. Main calendar display, recording,
reports, and analytics have separate fragments. Keep page-specific layout rules in
their component fragment, not in shared typography or settings rules. `background_images.qss`
handles uploaded backgrounds. Shared component tokens resolve solid and translucent
fills, borders, navigation, and tabs without a second set of control rules.
Material fragments are only for effects that cannot use these shared rules.
Define colors through theme tokens, not separate copies of component styles.
Keep role and state selectors explicit where their priority is needed. Hover,
selection, and disabled states must preserve dimensions and typography. List hover
feedback must not replace selection or disabled feedback. `PreviewListWidget`
applies the shared `list_style="preview"` role to framed lists and uses
`selection_style="subtle"` for project and revision selections. Underlined tabs
use `tab_style="underline"`; object names identify controls rather than defining
shared appearances. Preserve intentional ID selectors when they protect a
component variant from a more general hover or disabled rule.

Ordinary framed actions use neutral text and outlines; primary actions use accent
backgrounds and the highlighted text role. Destructive actions use the danger role.
Disabled states retain geometry and weight while using muted colors.
Selected navigation uses accent emphasis. Button icons follow their text color.

Qt object names use descriptive snake case and existing suffix conventions.
Icon-only actions need tooltips/accessibility names. Preserve keyboard navigation
and check long translated text. See [localization](localization.md).

## Theme Definitions

Add a `ThemeDefinition` to `config/themes.py` with a stable lowercase key,
a label marked with `N_`, light/dark `AccentColors`, and a `solid` or `glass`
material. Settings choices and configuration validation use this catalog;
customizable choices appear last. Translate new labels through the normal
gettext workflow.

`config/theme_colors.py` validates immutable color roles. Optional
`light_overrides` and `dark_overrides` use `SurfaceOverrides` to customize a few
surface or status colors without duplicating a material. Keep overrides limited
to genuine brand requirements and verify their contrast.

`theme/materials.py` defines reusable surfaces, calendar states, backdrop colors,
stylesheet fragments, and rendering capabilities. `palettes.py` combines these
with brand colors; `qt_palette.py` adapts resolved colors to Qt. Color resolution
and calendar rules do not require Qt. `component_tokens.py` resolves material
colors for controls and centralizes shared control heights, padding, and radii.
Use distinct control, panel, and item metrics rather than unrelated copies of the
same dimensions. Compact input metrics and inline action sizes also come from this
shared mapping; do not equate unrelated dimensions merely because they currently
have the same value. `stylesheets.py` owns cascade order, resource loading, strict
token substitution, and bounded caches. Identical fragment combinations share one
cached template.
Effects depend on material capabilities, not a theme's key.
Reuse these profiles for
branded themes rather than copying QSS or adding theme-name checks to widgets.
Apply application themes through `ThemeEngine.apply_to`. Custom-painted controls
use `theme/context.py` to read resolved colors; do not infer mode or material from
widget backgrounds, which can be transparent.
Check both color modes, contrast, interaction states, theme switching and
resource packaging when changing a theme or material.

Keep disabled control rules in `theme/qss/disabled.qss` and use the shared
disabled color roles. Custom painters and item delegates must honor the effective
enabled state, including a disabled parent. Preserve values, selection, geometry,
and typography when disabling controls; suppress hover feedback and restore the
normal appearance when they are enabled again.
Use shared component rules for hover feedback. Keep focused and selected states
distinct, avoid layout changes on hover, and limit active header styling to
headers that accept clicks. Custom date cells should repaint only the old and
new hovered cells without changing the selected date.

Shared hover and input focus rules live in `theme/qss/interaction_states.qss`,
after component rules and before disabled overrides. Preserve existing navigation
and selection styling; do not add a second outline to every focused control.
Retain native focus behavior where possible. Custom switches distinguish keyboard
focus from mouse focus and clear keyboard indicators when clicked. Focus feedback
must not change padding, dimensions, or the global palette.
Use native checked states for segmented controls. Refresh dynamic properties
through `set_style_property` only when their values change; updating a report
selection or an unchanged calendar must not repolish every item or header.
Settings navigation coalesces label layout with an owned single-shot timer.
Unchanged selections must not schedule another layout; font and style changes
must still update wrapping and minimum heights.
Shared sRGB calculations and color mixing belong to
`theme/color_contrast.py`, not individual widgets or theme definitions.

Apply accessibility improvements proportionately. Prefer descriptive control
names, keyboard focus feedback, and text alternatives that preserve the existing
layout and theme. WCAG 2.2 and the W3C WCAG2ICT guidance provide useful evaluation
criteria for this native application, but do not imply conformance. Some theme
color pairs and faded adjacent-month dates have insufficient contrast for those
criteria. Do not automatically recolor themes or change the application layout
solely to meet a numeric threshold; evaluate substantial visual changes separately.
Disabled controls are excluded from the WCAG minimum contrast requirements.

Check names and descriptions through Qt accessibility interfaces. Verify actual
screen-reader announcements, keyboard order, high-contrast mode, and text scaling
on the target OS. Screenshots alone cannot establish accessibility support.
See [WCAG2ICT](https://www.w3.org/TR/wcag2ict-22/) and
[text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

Full and minimal windows share `shell/appearance_controller.py` for theme
application, background styling, effects, and cleanup. Keep navigation and
account preferences in their respective shell controllers. Theme rendering must
not import window workflows or storage services. Prefer semantic color roles in
custom painting; explicit color overrides are for intentional fixed-color content.
`theme/widget_style.py` refreshes dynamic-property selectors without importing
application controls. Metric cards share `widgets/summary_card.py` and semantic
text roles; their charts live independently in `widgets/progress_visuals.py`.

Dialogs reuse the application-owned background runner unless one is explicitly
injected. Completion callbacks must tolerate a closed owner. Submission failures
must release pending handles and busy controls so users can retry without losing
their input. Completed backup and restore operations retain their bookkeeping
even when their originating settings view has closed.

Settings writes and classification/template updates run through the injected
background runner. Capture input before submission, serialize preference changes,
and apply returned state on the UI thread. Calendar record rows reuse existing
widgets; report histories share measurement layout and release offscreen text
documents without limiting the user's selected search range.

## Data and Resources

Use synthetic accounts and temporary databases. Never commit databases, exports,
credentials, logs, model weights, or generated builds.

Stored formats need an explicit compatibility/backup plan and regression tests.
Keep CSV semantics stable and preserve unsupported sources without mutation.
Add resources to the packaging manifest and check frozen paths.
Public deployment flags are separate from account settings and secrets.
New Windows credential files use local application data; retain an existing
credential directory and its keys when diagnosing a moved installation. See
[file locations](configuration.md#files-and-directories).

## Checks

Run the smallest relevant tests first, then broader checks as warranted:

```sh
python -m unittest tests.domain.test_worklog_rules -v
python -m ruff check worklogger scripts tests
python scripts/i18n/i18n_check.py
python scripts/build.py --check
git diff --check
```

See [testing](testing.md) for discovery, visual checks, and fixture isolation.
Changing Python/Qt/native dependencies also requires a consistent target build
and artifact checks, not just a successful import.
Continuous integration checks supported Python versions on Windows, Linux and
macOS ARM64, validates translations, runs ordinary tests and audits dependency
vulnerabilities. Separate build jobs verify platform archives after extraction
and upload the verified artifacts with dependency locks and checksum inventories.
Native visual checks remain opt-in.

## Documentation

Write user procedures or durable contributor contracts in English.
Describe supported behavior and operating procedures in neutral, professional
language. Exclude deployment-specific paths, credentials, and temporary records.
Add a guide only when its audience and responsibility cannot fit an existing one.
Published release history belongs in the changelog.
