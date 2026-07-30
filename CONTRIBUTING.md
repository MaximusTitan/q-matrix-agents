# Contributing to q-matrix-agents

**This repository is not currently accepting pull requests.**

That is a decision about maintainer bandwidth, not about openness. q-matrix-agents is the
reference implementation of the Q-Matrix pipeline and it moves in step with the research
behind it, so patches from outside are hard to land honestly. The code stays open under
**[Apache 2.0](LICENSE)** — use it, fork it, clone it, run it, build on it, ship something
derived from it. You do not need our permission and you do not need to ask.

## Where contributions are welcome

**[q-matrix-dataset](https://github.com/MaximusTitan/q-matrix-dataset)** is the repository
open for community contribution. Curriculum coverage, corrections, and new boards or
subjects all belong there. Read its own contributing guide before opening anything — data
contributions carry rights-attestation requirements that code does not.

## What you can still do here

- **Open an issue.** The tracker is open. Bug reports, reproducible failures, and
  questions about behaviour are all useful and get read. See
  [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) for the forms.
- **Report a vulnerability privately.** Not through the tracker — see
  **[SECURITY.md](SECURITY.md)**.
- **Fork it and change it.** If your fork diverges usefully, we would genuinely like to
  hear about it in an issue, even though we will not be merging it.

## If you are working in a fork

**[ARCHITECTURE.md](ARCHITECTURE.md)** is the source of truth for control flow, the KB
layout, agent responsibilities, and model routing. Read it before changing anything
structural. Two conventions matter more than the rest, because breaking either one causes
problems that surface far from the edit:

- **`skills/kb_access.py` is the sole owner of KB path knowledge.** Any new KB path,
  filename, or folder convention goes there and nowhere else. No agent, not the
  orchestrator, not `api.py`, not a test may construct a path from `KB_ROOT`.
- **Agents do not touch the filesystem and do not call each other.** An agent takes
  already-loaded data, returns data, and reaches the LLM only through `skills/llm.py`. The
  orchestrator decides what gets persisted. Control flow is one-way.

Setup lives in **[docs/SETUP.md](docs/SETUP.md)**; common first-run failures are in
**[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**.

Interaction in this repository's issues is covered by the
**[Code of Conduct](CODE_OF_CONDUCT.md)**.
