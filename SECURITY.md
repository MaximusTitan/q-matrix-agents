# Security Policy

## Reporting a vulnerability

Email **shrideep@prosoftpeople.com** with `[SECURITY]` in the subject line.

**Do not open a public GitHub issue for a vulnerability.** The issue tracker is public;
use it for functional bugs only. If you open an issue by mistake, delete the details and
email instead.

Include, where you can:

- what the issue is and where in the code it lives (file and, ideally, line)
- how to reproduce it, with a minimal invocation
- what an attacker gains — data, money, code execution, KB write access
- any suggested fix

**What to expect**

| | |
|---|---|
| Acknowledgement | within 5 business days |
| Assessment and remediation plan | within 15 business days of acknowledgement |
| Disclosure | coordinated; please hold public disclosure until a fix ships or 90 days pass, whichever comes first |
| Bounty | **none** — this project does not run a bug-bounty programme and cannot offer payment. Credit in the release notes is offered if you want it. |

This is a small project maintained alongside other work. Timelines are honest intent, not
a contractual SLA.

---

## Threat model / attack surface

Q-Matrix reads third-party curriculum documents, feeds them to LLMs, and writes the
results into a git repository that it then pushes. Each of those steps is a real attack
surface. The risks below are specific to this codebase and verified against it.

### 1. Prompt injection via untrusted curriculum documents — the headline risk

`skills/pdf_reader.py:extract_text_from_pdf` extracts raw text from third-party PDFs, and
that text is passed **directly** into agent prompts — `agents/map_extraction.py` feeds
`chapter.pdf` into the extraction call, and `skills/kb_access.py` concatenates curriculum
documents into the Generator's input.

**There is currently no sanitization, delimiting, or instruction-isolation layer.** A
malicious or tampered PDF can carry text that the model reads as instructions. Realistic
consequences:

- hijacking agent behavior — suppressing concepts, inventing skills, forcing a CSV that
  passes Check 1 and Check 2 while being wrong
- corrupting the KB, since a passing CSV is committed and pushed automatically
- poisoning prompts, because the Revision agent rewrites generation prompts from failure
  feedback derived from that same text
- attempting to exfiltrate surrounding prompt context into fields that get written to
  disk and rendered in the dashboard

Injected content also crosses chapters: prerequisite mapping (L1/L2/L3) reads other
chapters' confirmed CSVs, so a single poisoned chapter can influence its siblings and
later grades.

**Operator guidance:**

- Only ingest curriculum material from sources you trust and control. Treat every PDF as
  untrusted input, and prefer material you obtained yourself over material handed to you.
- Review generated CSVs before using them downstream. The checks are a quality gate, not
  a security control — they are themselves LLM calls over the same untrusted text.
- Keep `KB_ROOT` under version control (it already is) so injected changes are visible in
  a diff and revertible.

Hardening this — explicit untrusted-content delimiting, an injection detector, or a
sanitization pass in `skills/pdf_reader.py` — is known, unfinished work. This repo is not
taking pull requests (see [CONTRIBUTING.md](CONTRIBUTING.md)), so if you are running
Q-Matrix on material you do not fully control, treat that hardening as yours to add in
your fork.

### 2. LLM output is untrusted input

Generated CSV and JSON is parsed (`skills/csv_utils.py`), validated only for schema and
rule conformance, then written into the KB and served by `api.py` to the dashboard. Model
output is not authenticated content:

- downstream consumers must not treat a `confirmed_curriculum.csv` as verified fact
- prerequisite columns hold JSON-encoded structures produced by a model; parse them
  defensively
- anything rendered in a UI from these files should be escaped as untrusted text

### 3. API key handling

`AI_GATEWAY_API_KEY` (read in `skills/llm.py`) grants **billable** access to the Vercel AI
Gateway and, through it, to multiple model providers.

- Never commit `.env`. Confirm it is ignored before your first commit.
- Keep the key out of logs, screenshots, issue bodies, and PR descriptions.
- Rotate immediately on any suspected exposure — a leaked key is a direct financial loss,
  not just a data risk.
- `ANTHROPIC_API_KEY` is read only by `tests/test_skills.py`; the same rules apply.

### 4. The pipeline writes to and git-pushes a data repository

`skills/git_sync.py` runs `git pull --rebase` at the start of a run and a scoped
`git add` / `git commit` / `git push` at the end. This is automatic; `--no-sync` disables
both.

- Point `KB_ROOT` at a repository **you own and control**. Never at a shared or upstream
  repo you only have read intent for.
- Understand that every run **mutates and pushes** that repo using whatever git
  credentials the host has. The blast radius of a bad run is a commit on your KB remote.
- Concurrent runs share one working tree. `push_kb` deliberately scopes its pathspec to
  the chapter being run, but the underlying repo is still a shared mutable resource.

### 5. The FastAPI backend is unauthenticated

**Verified in `api.py`:** the only middleware is `CORSMiddleware` with
`allow_origins=["http://localhost:3000"]`. There are no `Depends`-based auth
dependencies, no API-key check, and no per-route guards on any of the ~20 endpoints —
including the write side (`POST /run`, `/reject`, `/re-extract`,
`/run-prerequisite-only`, `/run-l2-prerequisite`, `/run-l3-prerequisite`).

**It is intended for localhost development only, and must not be exposed to a network
without an authentication layer in front of it.** Note in particular:

- CORS is **not** access control. It constrains browsers, not `curl` or any other
  non-browser client. Every endpoint is fully reachable by anyone who can route packets
  to the port.
- The write endpoints spawn pipeline runs in background daemon threads, which mutate and
  push the KB repository under §4.
- `GET /kb/analytics/chapter/run/file` and the `/kb/*` browse endpoints read files out of
  `KB_ROOT` and return their contents.

If you must run it non-locally: bind to loopback and reach it over an SSH tunnel, or put
a reverse proxy with authentication in front and do not publish the port.

### 6. Cost as a denial-of-wallet surface

The write endpoints are the most expensive thing in the system. Measured across 685 run
records, a full pipeline run costs a median of **$0.32** (p90 $0.96, max $1.64), and
mapping a chapter across all three prerequisite stages runs about **$0.82** median.

An exposed `POST /run` therefore lets anyone spend your LLM budget, in a loop, at your
provider's rate limit. There is no rate limiting, quota, or per-caller accounting in
`api.py`. Treat exposure of the port as equivalent to leaking the gateway key, and set a
hard spend cap at the Vercel AI Gateway rather than relying on the application.

---

## Out of scope

- Curriculum content being pedagogically wrong. That is a quality issue — open a normal
  issue. The issue tracker stays open even though this repo does not take pull requests.
- Vulnerabilities in dependencies (`openai`, `pdfplumber`, `fastapi`, `uvicorn`, Next.js)
  with no Q-Matrix-specific amplification. Report those upstream; tell us if this codebase
  makes one meaningfully worse.
- Findings that require an attacker to already control `KB_ROOT`, the `.env`, or the host.
