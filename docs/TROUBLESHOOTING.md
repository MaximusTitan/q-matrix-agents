# Troubleshooting

Symptom → cause → fix. Error strings are quoted verbatim from the code so you can search
for them.

For first-time setup, start with **[SETUP.md](SETUP.md)**.

---

## `KB_ROOT` problems

### `EnvironmentError: KB_ROOT is not set. Add it to your .env file.`

```
EnvironmentError: KB_ROOT is not set. Add it to your .env file.
```

Raised by `skills/kb_access.py:24` at **import time**, so it fires before any work
happens — including when you run a test script or start `uvicorn`.

| Cause | Fix |
|---|---|
| No `.env` file | `cp .env.example .env`, then set `KB_ROOT`. There is no `.env` on a fresh clone. |
| Running from the wrong directory | `load_dotenv()` resolves `.env` relative to the working directory. Run from the repo root. |
| Variable set in a different shell | `.env` is read by the process, not exported to your shell. Confirm with `python -c "import os,dotenv;dotenv.load_dotenv();print(os.getenv('KB_ROOT'))"`. |

### KB looks empty: no boards in the dashboard, no chapters found

`KB_ROOT` is *set* but points somewhere wrong. This fails **silently** — nothing raises.
`api.py:_kb_textbooks_root()` returns `None` when `KB_ROOT/textbooks` does not exist, so
`/kb/boards` returns an empty list and the dashboard's board dropdown is blank.
`kb_access.list_textbook_chapters()` returns `[]` for the same reason, so L2/L3
eligibility reports `"eligible": false` with no blocking chapters.

Check:

```bash
python -c "import os,dotenv;dotenv.load_dotenv();print(os.getenv('KB_ROOT'))"
ls "$(python -c 'import os,dotenv;dotenv.load_dotenv();print(os.getenv("KB_ROOT"))')"
```

You should see `textbooks`, `curriculum-docs`, `rulesets` listed. Common mistakes:

- Pointing at `.../q-matrix-kb-template/textbooks` instead of the repo root.
- A relative path. Use an absolute path.
- A trailing quote or space captured into the value (`.env` does not strip quotes the way
  a shell does).
- Windows path in a WSL environment (or vice versa) — `C:\...` is not reachable from WSL
  as written.

---

## Missing curriculum or chapter files

### `FileNotFoundError: No curriculum docs found at: …`

```
FileNotFoundError: No curriculum docs found at: <KB_ROOT>/curriculum-docs/<board>/<subject>/<grade>
```

From `kb_access.load_curriculum_docs`. The folder does not exist. Either the path is
wrong, or one of the four names does not exactly match a folder on disk — see
[Folder naming](#folder-naming-mismatches).

### `FileNotFoundError: Curriculum docs folder exists but is empty: …`

```
FileNotFoundError: Curriculum docs folder exists but is empty: <path>
```

The folder exists but contains no file with a `.md`, `.txt`, or `.pdf` extension. Only
those three are read; anything else (`.docx`, `.csv`, a nested subfolder) is ignored and
counts as empty. Add at least one supported file.

### `FileNotFoundError: Chapter PDF not found: …`

```
FileNotFoundError: Chapter PDF not found: <KB_ROOT>/textbooks/<board>/<subject>/<grade>/<chapter>/chapter.pdf
```

From `kb_access.get_chapter_pdf_path`. The filename must be exactly `chapter.pdf` —
lowercase, no suffix. `Chapter.pdf`, `chapter04.pdf`, `chapter.PDF` will not be found (and
`chapter.PDF` *will* be found on case-insensitive macOS/Windows filesystems but not on
Linux, which makes it a portability bug — rename it).

### `FileNotFoundError: universal_rules.md not found at: …`

```
FileNotFoundError: universal_rules.md not found at: <KB_ROOT>/rulesets/universal_rules.md
```

The only manually authored input the system requires. It ships with the KB template; if
it is missing, your `KB_ROOT` is probably not a clone of the template.

---

## Folder naming mismatches

KB lookups are **exact string matches** against folder names. Nothing is normalised, and
nothing is fuzzy-matched — a mismatch surfaces as a `FileNotFoundError` for a path that
looks almost right.

| Mistake | What happens | Fix |
|---|---|---|
| `--grade Grade8` when the folder is `Grade 8` | `FileNotFoundError` on a `.../Grade8` path | Use the canonical form: `--grade "Grade 8"`. |
| `--grade Grade 8` (unquoted) | The shell splits it; `--grade` receives `Grade` and `8` becomes a stray positional, so argparse errors or the grade silently becomes `Grade` | Quote it. |
| `--chapter Chapter 4 Forces` (unquoted) | Same shell-splitting problem | Quote it: `--chapter "Chapter04_Exploring_Forces"`. |
| Chapter typo / wrong zero-padding (`Chapter4_…` vs `Chapter04_…`) | `Chapter PDF not found` | Copy the name from `ls` output, or pick it from the dashboard's KB browser, which lists real folder names. |
| `:` in a folder name (e.g. `Chapter04: Forces`) | The KB cannot be cloned on Windows at all — checkout fails on the illegal filename. Also breaks drive-sync tooling | Never use `: ? * < > \| "` or trailing dots/spaces in board, subject, grade, or chapter names. |
| Non-numeric grade folder (`Foundation`, `KG`) | `kb_access._grade_sort_key` finds no trailing digits and returns `(-1, name)`, sorting it **before every numeric grade**. L3 then treats it as an earlier grade for everything, pulling its chapters into every candidate pool — and its unmapped chapters block L3 eligibility subject-wide | Name grade folders with a trailing integer, or accept that non-numeric grades sort earliest. |

Whether a canonical grade folder is `Grade 8` or `Grade8` is a per-KB decision — the code
does not care, but you must be consistent, because `Grade 8` and `Grade8` are two
different chapters' worth of results. The published template uses `Grade 8` (with the
space).

---

## Git LFS not installed: PDF reads fail

### `PdfminerException: No /Root object! - Is this really a PDF?`

Or an empty/garbage extraction, or:

```
ValueError: No extractable text found in PDF: <path>
```

The `.pdf` on disk is a Git LFS **pointer file**, not a PDF. The KB repo LFS-tracks
`*.pdf`; cloning without LFS installed leaves ~130-byte text stubs in place of every PDF.

Confirm it:

```bash
head -c 60 "$KB_ROOT/textbooks/EXAMPLE_BOARD/EXAMPLE_SUBJECT/Grade 8/Chapter04_Exploring_Forces/chapter.pdf"
```

A pointer file starts with:

```
version https://git-lfs.github.com/spec/v1
```

A real PDF starts with `%PDF-`. Also telling: `ls -l` shows a file of ~130 bytes where a
chapter should be megabytes.

Fix:

```bash
git lfs install          # once per machine
cd "$KB_ROOT"
git lfs pull             # replaces every pointer with the real object
```

If `git lfs pull` reports missing objects, the PDFs were committed to the remote *without*
LFS by someone who also lacked it — the pointer is all that exists and the content must be
re-added.

Separately, a genuine PDF can still raise `No extractable text found` if it is a pure
scan with no text layer. `pdfplumber` does not OCR. Run OCR first (e.g. `ocrmypdf`) or
supply a text-layer PDF.

---

## API key and Gateway problems

`skills/llm.py` retries **only** `openai.RateLimitError` and
`openai.InternalServerError` — 3 attempts, 5 seconds apart. Every other
`openai.APIError` subclass (authentication, bad request, insufficient credit, connection
failure) is re-raised immediately with no retry.

| Symptom | Cause | Fix |
|---|---|---|
| `openai.AuthenticationError` / HTTP 401 on the first agent call | `AI_GATEWAY_API_KEY` missing, empty, or invalid. Note the client is constructed at import time from `os.getenv`, so a missing key does not fail until the first call | Set it in `.env`. Check for a stray trailing space or a truncated paste. |
| `GET /models` returns HTTP 502 `Failed to fetch model catalog: …` and the dashboard's model picker is empty | Same key problem, seen from `api.py`'s Gateway proxy — or genuine network trouble | Fix the key, restart uvicorn. The catalog is cached for 1 hour in-process; a stale cache is served in preference to erroring. |
| HTTP 402 / "insufficient credit" mid-run, partway through a chapter | Gateway account out of credit. Not retried — the run dies where it stands | Top up. Earlier attempts in that run were already billed. |
| `[llm] Rate limit hit (attempt 1/3). Retrying in 5s...` repeatedly, then `RuntimeError: LLM call failed after 3 attempts. Last error: …` | Sustained rate limiting — usually several pipeline runs in parallel against one key | Run chapters sequentially. Wait, then retry. `MAX_RETRIES` / `RETRY_DELAY` in `skills/llm.py` are the knobs if you must. |
| `RuntimeError: Model response had no tool call (finish_reason=…)` | The chosen model does not properly support forced tool use, or hit its output limit (`finish_reason=length`) | Pick a model tagged for tool use in the Gateway catalog. The default `anthropic/claude-sonnet-5` is known-good. |
| `openai.NotFoundError` naming a model id | A per-agent model override in the dashboard references a model the Gateway does not expose | Choose from the `/models` list rather than typing an id. |

---

## Git sync failures

### `RuntimeError: Git command failed: …`

```
RuntimeError: Git command failed: git pull --rebase
stderr: <git's message>
```

From `skills/git_sync.py:_run`. The orchestrator catches these around pull and push and
downgrades them to warnings, so you will usually see:

```
[orchestrator] Warning: KB pull failed — Git command failed: git pull --rebase
[orchestrator] Warning: KB push failed — Git command failed: git push
```

The run itself continues. A failed push means results exist only on your local disk.

| `stderr` says | Cause | Fix |
|---|---|---|
| `not a git repository` | `KB_ROOT` is a plain directory, not a clone | Clone the KB template properly, or use `--no-sync`. |
| `Permission denied` / `403` / `remote: Write access ... not granted` | You do not have push rights — typically because you cloned the upstream template instead of your own fork | Fork it and point `KB_ROOT` at your fork, or use `--no-sync`. |
| `could not apply …` / `CONFLICT` | The rebase hit a conflict against remote changes | Resolve it manually in `KB_ROOT` (`git status`, `git rebase --continue`), or `git rebase --abort` and run with `--no-sync`. |
| `HEAD detached at …` | The KB clone is on a detached HEAD, so there is no branch to push | `cd "$KB_ROOT" && git checkout main`. |
| `no upstream configured` | The current branch has no tracking branch | `git push -u origin <branch>` once, manually. |
| `src refspec … does not match any` / nothing pushed | Nothing to push. `push_kb` only stages this chapter's own paths and skips entirely if `git status --porcelain` on them is clean — you will see `[git_sync] No KB changes to push.` | Not an error. |

**The blanket fix is `--no-sync`**, which disables both the pull and the push. Commit and
push the KB yourself when you are ready.

Note that the dashboard and every API endpoint already default to `no_sync: true`, so
runs started from the UI never touch git. If you expected the dashboard to push your
results, it did not — that is by design.

---

## Dashboard shows no data, or the live stream is dead

Work down this list in order:

1. **Is the backend up?** `curl http://localhost:8000/kb/boards` should return JSON.
   Nothing listening means `uvicorn api:app --reload --port 8000` is not running, or
   crashed at import — check that terminal for `EnvironmentError: KB_ROOT is not set`.
2. **Is `NEXT_PUBLIC_API_URL` set?** `dashboard/src/lib/api.ts` falls back to `""` when it
   is unset, making every request a *relative* path — so the browser calls the Next.js
   server on :3000, which has no such routes, and everything 404s. Fix:
   `cd dashboard && cp .env.local.example .env.local`, then **restart `npm run dev`**.
   `NEXT_PUBLIC_*` values are inlined at build time; editing the file without restarting
   changes nothing.
3. **Port mismatch.** If you started uvicorn on a port other than 8000, `.env.local` must
   match.
4. **CORS.** The backend allowlists exactly `http://localhost:3000` (`api.py:52`). If Next
   started on 3001 because 3000 was taken, every request fails with a CORS error in the
   browser console. Free port 3000, or run `npm run dev -- -p 3000`. Also note
   `127.0.0.1:3000` is a *different* origin from `localhost:3000` and is not allowlisted —
   use `localhost`.
5. **SSE connects but no events arrive.** Heartbeats (`{"type":"heartbeat"}`) every second
   with no pipeline events means the run thread died. Check the uvicorn terminal — it
   prints `[api] ✗ CRASH run <id>: <error>` plus a full traceback for any exception in a
   run.
6. **HTTP 404 `Run not found` on `/stream/{run_id}`.** The run id is unknown to the event
   bus, which is in-process and in-memory. Restarting uvicorn (including `--reload`
   restarting it for you when you edit a file) discards every run id. Start a new run.
7. **Analytics is empty.** It reads `run.json` files under `KB_ROOT`. A KB with no
   completed runs has nothing to show.

---

## A chapter escalates every time

Escalation is a designed outcome, not a crash: the eval loop spent its attempt budget or
stopped improving. The orchestrator prints:

```
Pipeline failed after <n> attempt(s).
Report folder: <KB_ROOT>/escalations/<board>/<subject>/<grade>/<chapter>/<date>
```

and exits with code `1`. That folder is a self-contained snapshot — `report.md` (readable
summary), `run.json` (structured record), and every attempt's prompt and CSV. Escalation
folders accumulate by date, so the failure history is preserved.

Read `report.md` first: it names which check failed and lists the feedback, including
`missing_concepts` / `missing_skills` for a Check 2 coverage failure. Then choose:

| What `report.md` shows | Action |
|---|---|
| Check 2 coverage gaps — real concepts the CSV missed | Re-run with `--human-feedback "…"` naming what to add. One extra revision cycle. |
| Check 1 rule violations the model keeps repeating | Re-run with `--reject --reason "…"` to write the rule permanently into `rulesets/{board}/{subject}/{grade}/rules.md`, so Eval enforces it on all future runs for that grade. |
| The *concept-skill-map itself* is wrong — concepts merged, split badly, or hallucinated from a bad PDF extraction | `--re-extract --map-guidance "…"`. Fixing the CSV cannot fix a bad map, and Check 2 measures the CSV against that map. |
| Nothing coherent, or extracted text looks like garbage | Check the chapter PDF. An LFS pointer or a scanned-image PDF produces meaningless input; see [Git LFS](#git-lfs-not-installed-pdf-reads-fail). |

Every escalated attempt was billed. A chapter that escalates repeatedly is one of the
more expensive things you can do — see [SETUP.md §10](SETUP.md#10-cost).

---

## L2 / L3 refuses to run

```
HTTP 400: Not every chapter in <board>/<subject>/<grade> has L1 prerequisites mapped yet
— L2 mapping is not available.
```

```
HTTP 400: Not every chapter in every grade earlier than <grade> (same <board>/<subject>)
has L1 prerequisites mapped yet — or there are no earlier grades — L3 mapping is not
available.
```

These gates are intentional: L2 and L3 need a complete candidate pool. Query the
eligibility endpoint to see exactly what is blocking:

```bash
curl "http://localhost:8000/kb/l2-eligible-chapters?board=EXAMPLE_BOARD&subject=EXAMPLE_SUBJECT&grade=Grade%208"
```

`blocking_chapters` lists the chapters still lacking L1 prerequisites — run the full
pipeline on each, then retry. For L3, also check `prior_grade_count`: if it is `0`, there
are no earlier grades in the KB and L3 can never be available for that grade.

Note L3's alias behaviour — `Science` also scans `Environmental Science` for earlier
grades (`kb_access._PREREQ_SUBJECT_ALIASES`), so unmapped EVS chapters can block Science's
L3 even though they are a different subject folder.

---

## Tests fail on a fresh clone

Expected. `tests/` is **not a pytest suite**: all eight files are standalone scripts with
module-level `assert`s, zero `def test_*` functions, and `pytest` is not in
`requirements.txt`. Running `pytest tests/` collects nothing useful.

Run them individually:

```bash
python tests/test_prerequisite_l3.py
```

On an empty KB, only `test_prerequisite_l3.py` passes — it exercises pure logic and needs
`KB_ROOT` merely to be *set*, not to point anywhere real, and makes no LLM calls.

`test_skills.py`, `test_validation.py`, and `test_map_extraction.py` **fail** (they do not
skip) without curriculum docs and chapter PDFs in the KB — typically with the
`FileNotFoundError`s documented above. `test_skills.py` also reads `ANTHROPIC_API_KEY`,
which nothing else in the repo uses.

Several tests — `test_map_extraction.py`, `test_generator.py`, `test_eval.py`,
`test_generator_eval.py`, `test_revision_loop.py` — make **real, billable LLM calls**.
Do not run them casually or in a loop.

If a test fails with `ModuleNotFoundError: No module named 'skills'`, run it from the repo
root; the scripts insert the parent directory onto `sys.path` relative to their own
location, but the working directory still matters for `.env` discovery.
