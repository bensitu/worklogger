# Integrations

## Availability

An implemented adapter is not necessarily connected to the default desktop.
`worklogger/bootstrap.py` is the authoritative composition entry point.
`SettingsCapabilities` communicates actual generation and proxy availability to
the settings surface. Local generation is connected through the optional native
backend; account proxy transport and external generation are connected. Local model and proxy preferences can be enabled and
configured beforehand; their switches show saved intent rather than runtime readiness.
External endpoint,
model identifier, and securely stored API-key configuration remain editable without
activating or contacting a service.
File management is independent and remains available only when its workflow is
connected. Capability declarations do not create adapters or route requests.

| Component | Implementation | Default desktop behavior |
| --- | --- | --- |
| Public holidays | `PythonHolidaysProvider` | Connected, using IANA timezone countries or an explicit account region |
| Release checks | `GitHubReleaseUpdateChecker` | Connected to the manual update action |
| Model files | `JsonLocalModelStore` | Connected to local model management |
| External AI | `AccountAIGateway` and `OpenAICompatibleGateway` | Explicit account opt-in; configured endpoint/model/key are used by rewriting and chat handlers |
| Local AI | `LocalInferenceRuntime` and `LocalModelGateway` | Connected when the native dependency and a selected verified model are available; controlled by account preferences |
| Identity providers | OIDC/PKCE and provider helpers | Desktop constructs disabled Google/Microsoft providers |
| Proxy preferences | `AccountHTTPTransport` and system credential storage | Applied to update checks, model catalog/file downloads, and external AI |

## AI Services

Recording, notes, reports (including the compatibility dialog), chat and sample
connection checks run text-processing requests in background jobs with visible
indeterminate progress and cancellation. Cancellation prevents applying a late
response, but does not guarantee immediate termination of a native inference or
provider request. Inputs are not automatically saved. Stable disabled actions
indicate unavailable services without shifting the recording layout during startup.

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
It does not read an API key automatically from environment variables. The account
switch `external_model_enabled` defaults to false for new and existing accounts;
enabling it selects external processing explicitly. Saving configuration alone
does not send a request. Test sends only sample text, not work records. External
configuration or request failures never silently fall back to another provider.

The local adapter calls an injected Python generator with messages and an output
token limit. It does not load GGUF files itself. `RoutingAIGateway` can coordinate
two supplied adapters. Model management, model loading, and request routing are
separate responsibilities. Desktop composition injects a lazy CPU engine into the
local adapter. `AccountAIGateway` selects external processing only when explicitly
enabled; otherwise it uses the local adapter. A local failure never causes remote
transmission. Both handlers share the account routing policy and privacy controls.

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
Cancellation leaves a partial file for a later retry. Verification results and
parsed catalogs are cached by path, file timestamps, size, and expected checksum
where applicable.
A remote catalog is used when `WORKLOGGER_MODEL_CATALOG_URL` supplies an explicit
HTTPS URL, or a programmatic caller passes one to the store constructor. Entries
used for downloads must contain a SHA-256 checksum. The desktop reads the bundled
catalog and merges persistent metadata by ID. Refresh without a remote URL reads
these local resources; it does not contact Hugging Face. Repository revision URLs
and digests pin the supplied download files. See [local models](local-models.md).
Failed remote refresh returns an error and leaves cached entries intact; listing
and managing the local catalog remains available without a network connection.

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
Account creation and identity binding use one SQLite transaction. A failed binding
cannot leave a partial account, and bounded random-name retries handle collisions.

## Network and Platform Services

The release checker contacts the configured GitHub releases API with a timeout
and response-size limit. It reports a newer version; it does not install it.
Model and external-AI adapters contact the supplied URLs when invoked. Holiday
lookup uses the installed `holidays` package rather than an online calendar feed.
Automatic country detection reads the bundled `tzdata` zone table. Unknown or
country-neutral zones do not fall back to US holidays. General settings provide
an ISO country selection and supported state/province codes, stored together as
one account preference. Subdivision support follows the installed holiday library.
See the [tzdata resource layout](https://tzdata.python.org/) and
[holiday region API](https://holidays.readthedocs.io/en/latest/api/).

The shared HTTPS transport uses the certifi certificate bundle and disables
implicit environment/system proxies. Release and model requests require public
destination addresses, including redirect targets and the actual connected peer.
The Network settings form configures `AccountHTTPTransport`, not a global OS proxy.
When enabled, an HTTP CONNECT proxy carries HTTPS requests and their redirects;
certificate verification still authenticates the destination. Public requests
validate public destination DNS addresses before tunneling instead of incorrectly
treating the trusted proxy's private address as the destination. The configured
proxy is trusted to resolve and forward the destination correctly. Direct traffic
continues to validate the connected peer. Implicit environment/system proxies
remain disabled to prevent unrequested routing or disclosure.

Address fields accept a host or `http://host` plus a separate port. Optional Basic
proxy authentication uses the system credential store; a domain prefixes the
username as `domain\\username`. SOCKS, HTTPS-to-proxy transport, NTLM, and automatic
proxy discovery are not supported. Proxy authentication over HTTP requires a
trusted network. Invalid/incomplete enabled configurations fail rather than
silently bypassing the proxy. New settings apply on the next request.

Tray residency is implemented for Windows, menu-bar residency for macOS, and is
conditional on Qt reporting a tray service. Linux residency is not enabled by the
current platform mapping. Application icons and platform residency are separate
features.

## Adding a Connected Service

Define the contract in the application/domain layer, implement it in infrastructure,
and construct it in the appropriate `composition/` feature module, called by
`bootstrap.py`. Add secure credential access,
availability reporting, privacy controls, timeout/cancellation handling, and tests
with injected transports. Run blocking network and inference work through the
job runner. Keep disabled UI controls disabled until the complete workflow works.
