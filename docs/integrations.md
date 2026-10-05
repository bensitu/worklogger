# Integrations

## Availability

An implemented adapter is not necessarily connected to the default desktop.
`worklogger/bootstrap.py` is the authoritative composition entry point.

| Component | Implementation | Default desktop behavior |
| --- | --- | --- |
| Public holidays | `PythonHolidaysProvider` | Connected, using the system-timezone country mapping |
| Release checks | `GitHubReleaseUpdateChecker` | Connected to the manual update action |
| Model files | `JsonLocalModelStore` | Connected to local model management |
| External AI | `OpenAICompatibleGateway` | Not supplied to the chat or rewrite handlers |
| Local AI | `LocalModelGateway` | Requires an injected generator; not supplied by desktop startup |
| Identity providers | OIDC/PKCE and provider helpers | Desktop constructs disabled Google/Microsoft providers |
| Proxy preferences | Settings and system credential storage | Saved, but not applied to the HTTP adapters |

## AI Services

The `AIGateway` protocol takes `AIRequest` and returns `Result[AIResponse]`.
`AiChatHandler` and `RewriteTextHandler` accept a service and model identifier.
Without one they return an unconfigured-service result. The generic default model
identifier is not a provider model selection; an integration must supply one.

The external adapter sends model/messages JSON to `<base_url>/chat/completions`
using an injected API credential and HTTP opener. It applies timeouts, a bounded
response size, and retries only DNS or connection-refused failures before a connection is established.
HTTP errors, read timeouts, and invalid responses are not retried. Redirects are
rejected to prevent forwarding credentials. Error details retain only exception
types, HTTP status, and bounded machine-readable error codes, not response messages.
It does not read an API key automatically from
environment variables or enable itself from the Settings page.

The local adapter calls an injected Python generator with messages and an output
token limit. It does not load GGUF files itself. `RoutingAIGateway` can coordinate
two supplied adapters. Model management, model loading, and request routing are
separate responsibilities.

AI context includes records within a daily, weekly, or monthly period. Privacy
switches control notes, quick logs, and calendar content; working-hour context is
still included. Queries are bounded to the selected period, and excluded categories
are not fetched. Settings-read failures stop context construction. Context is limited
to 40,000 characters; larger selections are rejected, not silently truncated. Weekly
ranges follow the account's week-start setting. Context and
conversation history are user data, not executable instructions.

## Local Models

The desktop store is `models/` beside the database and is shared between accounts
using that database directory. Selection is an account setting. Imported files
must be nonempty `.gguf` files; metadata records a computed SHA-256 digest.
Verification checks existence, size, and a required checksum, not inference
quality or semantic validity of a model.

Downloads require a catalog SHA-256 checksum. A per-file lock protects resumable
partial files; range and response lengths are validated. Servers ignoring ranges
restart the transfer. Only a matching complete file replaces the destination.
Cancellation leaves a partial file for a later retry. Verification results are
cached by path, file timestamps, size, and expected checksum.
A remote catalog is only used when
an explicit URL is passed to the store constructor; desktop startup does not pass
one. Refresh therefore reads local metadata by default. The root catalog file is
not automatically copied into runtime storage.

Selection requires a verified file. Deletion considers account selections through
the settings usage reader. Copy model files and metadata separately when moving
an installation; database backup does not include them. Model licenses and
hardware suitability remain the distributor's responsibility.

## Identity Providers

Identity helpers include provider normalization, configuration parsing, PKCE,
OIDC handling, and linked-identity storage. The configuration helper can read
`WORKLOGGER_IDENTITY_CONFIG` and selected provider environment values such as
`WORKLOGGER_GOOGLE_CLIENT_ID` and `WORKLOGGER_FIREBASE_API_KEY`.

These helpers are not connected to the disabled desktop login buttons. Changing
those environment values alone does not enable federated login. Linking an
external identity record is also separate from obtaining an authenticated local
application session. Do not advertise provider login until that end-to-end flow
is connected and tested.

OIDC profile construction accepts a signed token, not an arbitrary claim mapping.
It verifies RS256 against supplied trusted JWKS, issuer, audience, required expiry
and issue time, subject, and a nonempty expected nonce. JWKS must come from the
configured provider through a trusted HTTPS integration, never from token-supplied
URLs. Microsoft configuration requires a concrete tenant. Firebase response
conversion verifies the signed project token and subject/provider agreement;
the broker workflow must still bind its original OAuth request and response.
Validation uses [PyJWT's supported verification API](https://pyjwt.readthedocs.io/en/stable/usage.html).
New external accounts use a separate collision-resistant name when a local name
is occupied and do not have a usable random local password. Removing the last
identity requires another usable password or identity.

## Network and Platform Services

The release checker contacts the configured GitHub releases API with a timeout
and response-size limit. It reports a newer version; it does not install it.
Model and external-AI adapters contact the supplied URLs when invoked. Holiday
lookup uses the installed `holidays` package rather than an online calendar feed.

The shared HTTPS transport uses the certifi certificate bundle and disables
implicit environment/system proxies. Release and model requests require public
destination addresses, including redirect targets and the actual connected peer.
The Network settings form does not install a global proxy or configure this
transport. A connected proxy integration must be supplied explicitly.

Tray residency is implemented for Windows, menu-bar residency for macOS, and is
conditional on Qt reporting a tray service. Linux residency is not enabled by the
current platform mapping. Application icons and platform residency are separate
features.

## Adding a Connected Service

Define the contract in the application/domain layer, implement it in infrastructure,
and construct it explicitly in `bootstrap.py`. Add secure credential access,
availability reporting, privacy controls, timeout/cancellation handling, and tests
with injected transports. Run blocking network and inference work through the
job runner. Keep disabled UI controls disabled until the complete workflow works.
