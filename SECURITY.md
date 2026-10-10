# Security Policy

## Supported Versions

Security fixes are applied to the latest published version of WorkLogger.

The version in source metadata may not yet correspond to a published release.
See the [changelog](CHANGELOG.md) for current behavior and
[security and privacy](docs/security.md) for storage and credential limitations.

Dependencies are pinned for reproducible installations, not automatic security
updates. Check direct and transitive dependency advisories before publishing a
release and when a relevant vulnerability is reported. Apply applicable updates
with focused compatibility/security tests; do not infer protection from a version
pin alone. Optional native inference dependencies need the same review.

## Reporting a Vulnerability

Please do not open a public issue for security-sensitive reports.

Instead, contact the maintainer privately through GitHub and include:

- A clear description of the issue
- Steps to reproduce
- Impact assessment
- Any suggested mitigation if available

You can expect an initial response as soon as reasonably possible. After the issue is confirmed, fixes will be prepared and disclosed responsibly.

Do not include live credentials, recovery keys, session files, personal databases,
or unredacted logs in the initial report. Use synthetic records when possible.
Provide the affected application, Python, Qt, and operating-system versions, and
identify whether the problem occurs in a source run or a packaged application.
