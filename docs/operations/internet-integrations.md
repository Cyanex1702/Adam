# Internet and integrations (Wave 14)

Open **Internet** after signing in as the PC owner. Enter your owner passphrase
and choose **Enable Internet for this login**. Access starts off on restart and
for every new login. Disable clears provider connections, page drafts and action
receipts held in RAM. Nothing from this view becomes ordinary memory or RAG.
Queries, requested URLs and reviewed arguments are sent to the chosen service;
do not include personal information you do not want that service to receive.

## Search and evidence

Hacker News via Algolia searches technology/community stories and works without
an API key. Wikipedia full-text searches encyclopedia articles; the service may
reject requests (HTTP 403 observed from this PC during QA). General web search
is available through an owner-selected public HTTPS SearXNG `/search` endpoint
with JSON enabled. No instance is silently selected or hosted for you. Public
instances can disable JSON, rate-limit or reject access. See the official
[SearXNG search API](https://docs.searxng.org/dev/search_api.html),
[Hacker News search API](https://hn.algolia.com/api) and
[MediaWiki search API](https://www.mediawiki.org/wiki/API:Search).

Fetch a public HTTPS HTML/text URL directly when you have a source. Results show
the source URL, fetch time, available source date, content hash and untrusted-data
label. Search dates belong to an external index; fresh retrieval does not prove
fresh publication or factual accuracy. Search excerpts are shown directly, with
no generated factual answer and no mixing with local memories. Ordinary chat
does not browse or automatically consume these excerpts.

Network access uses TLS certificate verification with DNS-address pinning and
the original hostname for SNI. All resolved addresses must be public; localhost,
LAN, reserved, link-local, multicast and IPv6 transition destinations are denied.
Each redirect is revalidated; at most three redirects follow the initial request.
Only HTTPS port 443 is supported. No proxy environment, cookies, owner session
tokens, browser profiles or ambient credentials are forwarded. Responses have
a one-MiB bound and an application deadline of twenty seconds after resolution;
OS DNS resolution can take longer. Gzip/deflate decoding has the same one-MiB output bound. Other encodings, binary content and obvious
credential-bearing input/output are denied. The existing secret detector is
heuristic, not a complete personal-data classifier.

## Text browser

**Open text browser** reads fetched HTML without running scripts. Follow a listed
link to navigate. Simple input fields support **Fill locally**, which changes a
RAM draft without submitting it. Then choose **Preview submission**, review its
destination, method and exact fields, enter your owner passphrase and choose
**Approve and execute this action**. Both GET and POST form submission require
approval. Editing the draft, navigating or changing the remote page invalidates
its old preview. The source page is fetched again before submission and its
hash must match. Results remain untrusted; a response is not proof of the
external effect. Check the actual service when a result is uncertain.

This is an HTML text browser, not a graphical JavaScript browser. No account
profiles, login forms, passwords, file uploads, arbitrary downloads, JavaScript,
CAPTCHA solving or OS mouse/keyboard control are supported. Sensitive fields,
duplicate field names, unsupported controls/encodings and cross-origin form
destinations are denied. Download-like binary responses are rejected rather
than written to disk. Dynamic websites may need your regular browser. Full
graphical computer-use behavior belongs to later waves.

## External providers

Enter an HTTPS MCP endpoint and a comma-separated exact tool allowlist. Enter
your owner passphrase and choose **Connect and discover**. Only those names
become available. Remote descriptions, schemas, annotations and results are
untrusted. An annotation cannot lower risk or approve an action. Enter JSON
arguments, create a preview, review it, reauthenticate and explicitly execute.
Credential-style JSON keys are denied recursively, including camelCase and nested fields.
They are not an authentication channel; credentialed providers need a future vault-backed adapter.
All external calls are treated as potentially side-effecting, including tools
that describe themselves as read-only. Previews expire after five minutes.
Schemas are checked again immediately before calls; changes require reconnecting.
Disconnect removes capabilities and cancels associated pending work. Failed or
uncertain execution detaches the provider. There is no automatic retry.

The supported adapter is a bounded
[MCP 2025-11-25 Streamable HTTP tools subset](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports):
initialize, initialized notification, tools/list and tools/call. JSON and bounded
SSE result responses are accepted. No stdio process, roots, sampling, elicitation,
resources, OAuth/credential setup, paginated discovery, legacy SSE endpoint,
resumable stream or 2026 protocol adapter is included. Reference-based, recursive,
combinator and regex schemas are denied; use simple object/primitive schemas.
At most five providers, twenty declared names per connection, one hundred
discovered tools and one hundred action receipts per enabled workspace are kept.
Disable/re-enable clears the workspace when its limits are reached.

ADAM's client enforces which remote method/name/payload it sends and exposes no
local file/process capabilities to servers. It does not sandbox a remote
server's implementation or control what that server does after receiving a
call. Use only trusted endpoints and review their behavior. A harmless example
is [DeepWiki's public MCP server](https://mcp.deepwiki.com/) at
`https://mcp.deepwiki.com/mcp`, declaring only `read_wiki_structure` with
`{"repoName":"python/cpython"}`. Its documentation output is reported evidence.

## Cancellation and audit

Cancel a preview, approved action or running action; disable Internet to cancel
the entire workspace. Cancellation suppresses future sends and result publication
at checked boundaries. A request already sent cannot be recalled, so cancelled
in-flight side effects are **UNCERTAIN**. Never automatically retry that action;
verify the external service first. Execution consumes an approval once, even
after failure. Server requests, page instructions and tool outputs never grant
ADAM permissions or execute local tools.

Audit traces persist identifiers, event/status/error codes, not page text, URLs,
arguments, schemas or credentials. Action details and pages stay in RAM and are
bound to the current owner login. Guest, demo and phone clients have no Internet
API capability. Visibility/unmount guards clear UI content and prevent late
responses from repopulating a locked/hidden view. Existing private stores and
backup schemas are unchanged. No new model, GPU workload or browser installation
is required. External-provider or network failure leaves the local core usable.
