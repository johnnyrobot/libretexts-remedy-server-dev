# LibreTexts Remedy — full stack deployment

**Start here if you were handed more than one `remedy` repository and are not sure how they fit together.**

Remedy is three separately-versioned services that ship as one stack. This
directory contains the only `docker-compose.yml` that runs all three, plus the
environment templates for each.

---

## The three repositories

| Repository | Language | Role | Runs as |
|---|---|---|---|
| **`libretexts-remedy-server`** | Python / FastAPI | The engine. All accessibility checking, remediation, and PDF/Office conversion lives here behind `/v1/*`. Every other component is a client of it. | long-lived HTTP service |
| **`libretexts-remedy-bridge`** | TypeScript / Node | CXone Expert page I/O. Reads page HTML from CXone, previews AI-assisted fixes, writes approved revisions back through guarded APIs. | long-lived HTTP service |
| **`adapt-a11y-scanner`** | TypeScript / Node | Renders ADAPT questions in headless Chromium (waits for MathJax), captures the real DOM, and posts it to the server for scanning. | HTTP service *or* one-shot CLI job |

You do **not** need all three. Pick by what you are scanning:

| I want to… | Clone | Skip |
|---|---|---|
| Remediate PDFs / Office docs, or validate raw HTML | `libretexts-remedy-server` only | bridge, scanner |
| Remediate **CXone Expert pages** (library content) | server + **bridge** | scanner |
| Scan **ADAPT questions** for WCAG issues | server + **scanner** | bridge |
| Run the Conductor accessibility matrix | all three | — |

---

## Topology

```
                        ┌───────────────────────────┐
   CXone Expert  ◄─────► │  remedy-bridge  :5175     │
   (page HTML,           │  reads/writes page HTML   │
    guarded writes)      └────────────┬──────────────┘
                                      │ HTTP
                                      ▼
   ADAPT          ┌──────────────────────────────────┐
   (questions) ◄──┤  remedy-server  :8000            │◄─── Conductor
                  │  /v1/* — checkers, fixers,       │     (PROJECT_REMEDY_BASE_URL)
                  │  converters, HTML validation     │
                  └────────────▲─────────────────────┘
                               │ HTTP (POST rendered DOM)
                  ┌────────────┴─────────────────────┐
                  │  adapt-scanner  :5176            │
                  │  headless Chromium + MathJax wait│
                  └──────────────────────────────────┘

  All three attach to the external Docker network `libretexts_remedy`,
  which Conductor also joins.
```

`remedy-server` is the hub. The bridge and the scanner never talk to each other.

---

## Deploy from scratch

### 1. Clone all three as siblings

The compose file resolves build contexts relative to itself, so the directory
names and layout matter:

```bash
mkdir remedy && cd remedy
git clone https://github.com/johnnyrobot/libretexts-remedy-server-dev.git   libretexts-remedy-server
git clone https://github.com/johnnyrobot/libretexts-remedy-bridge-dev.git   libretexts-remedy-bridge
git clone https://github.com/johnnyrobot/adapt-a11y-scanner-dev.git         adapt-a11y-scanner
```

> The GitHub repositories carry a `-dev` suffix; the local directories must not.
> Clone with the explicit target name shown above.

### 2. Create the shared network

Conductor and this stack both declare `libretexts_remedy` as `external`, so
neither owns it. Create it once:

```bash
docker network create libretexts_remedy
```

### 3. Fill in the environment files

```bash
cd libretexts-remedy-server/deploy/stack
cp env/remedy-server.env.example  env/remedy-server.env
cp env/remedy-bridge.env.example  env/remedy-bridge.env
cp env/adapt-scanner.env.example  env/adapt-scanner.env
```

Then edit each. Every value marked `REPLACE_WITH_*` must be set — placeholders
do not fail loudly, they fail as `403` or `503` at scan time. See
**Required credentials** below for what each one is.

`env/*.env` is gitignored. Only the `.example` files are tracked.

### 4. Build and start

```bash
docker compose up -d --build
```

### 5. Verify

```bash
curl -fsS http://127.0.0.1:8090/readyz     # remedy-server: SQLite + job dir + worker
curl -fsS http://127.0.0.1:8092/healthz    # remedy-bridge
docker compose exec adapt-scanner \
  node -e "fetch('http://127.0.0.1:5176/healthz').then(r=>console.log(r.status))"
```

All three healthy → the stack is up. Scan something real:

```bash
# CXone page (needs the bridge)
docker compose exec remedy-bridge \
  node packages/cli/dist/index.js scan <page-url>

# ADAPT question (needs the scanner)
docker compose run --rm adapt-scanner node dist/index.js question 1234
```

---

## Required credentials

Only variable **names** are listed here. Values come from your own accounts —
none are shipped in these repositories.

| Service | Variable | What it is |
|---|---|---|
| server | `APP_API_KEY` | Shared secret. The scanner sends the identical value as `X-API-Key`. |
| server | `OLLAMA_API_KEY`, `OLLAMA_BASE_URL` | LLM backend for AI-assisted fix suggestions. |
| server | `CORS_ALLOW_ORIGINS` | Origins allowed to call `/v1/*` from a browser (Conductor's URL). |
| bridge | `SERVER_KEY`, `SERVER_SECRET`, `SERVER_USER` | CXone Expert (MindTouch) service-account triple. Without real values, page fetches return **403**. |
| bridge | `REMEDY_WRITE_ALLOWLIST` | Regex of namespaces the bridge may write to. Defaults to `^Sandboxes/`. **Widen deliberately.** |
| scanner | `ADAPT_TOKEN` | ADAPT service-account JWT, set as the `token` cookie. Preferred over email/password. |
| scanner | `REMEDY_API_KEY` | **Must equal the server's `APP_API_KEY`.** Mismatch → every scan 401s. |

---

## Five things that will bite you

1. **The server must run the `runtime` target, not `runtime-slim`.**
   `runtime-slim` omits the Playwright/Chromium layer (`COPY --from=playwright
   /root/.cache/ms-playwright`) that `runtime` includes. Without a browser,
   `/v1/validate/html` returns `503` — and that is the exact endpoint the
   scanner posts to. The compose file in this directory pins `target: runtime`;
   keep it that way if you write your own. Use `runtime-slim` only for
   PDF/Office work with no HTML validation and no ADAPT scanning.

2. **`REMEDY_API_KEY` and `APP_API_KEY` are the same secret in two files.**
   They live in `env/adapt-scanner.env` and `env/remedy-server.env`
   respectively. Nothing validates that they match until a scan fails with 401.

3. **The `libretexts_remedy` network must exist before `up`.** It is declared
   `external` by both this stack and Conductor so that neither deletes it on
   `down`. If compose reports `network libretexts_remedy declared as external,
   but could not be found`, you skipped step 2.

4. **Bridge writes are dry-run by default, and that is deliberate.** `fix` and
   `pipeline` require both `--apply` and an interactive per-page `y/N`. Before
   any write the bridge snapshots the full before-HTML to
   `.remedy/snapshots/{pageId}/`, and CXone keeps its own revision history — two
   independent rollback paths. `remedy revert <page>` uses the first one.

5. **Conductor needs one unrelated patch to work with this stack.** Its
   `getTOC` Origin allowlist rejects non-`libretexts.org` hosts. Set
   `LIBRETEXTS_TOC_ORIGIN=https://libretexts.org` in Conductor's environment;
   `server/util/bookutils.js` reads it.

---

## Reproducing the demo

The demo video that accompanies these repositories shows the Conductor accessibility matrix on an
82-page book cloned into a CXone sandbox: scan results per page and WCAG criterion, a targeted-fix
preview with an HTML diff, and a work item whose evidence was cleared by a bridge tag restore. To
reproduce it:

1. **Bring up all three services** (steps 1–5 above) and confirm `/readyz`, `/healthz` and the
   scanner health all answer.
2. **Patch Conductor** with `conductor-remedy-patch` (twelve `git am` patches: the matrix,
   the remediation work queue with per-page bridge actions, the WCAG verification panel, and
   a CORS fix for browser-driven scans). Set `LIBRETEXTS_TOC_ORIGIN` (bite 5) and point
   Conductor's Remedy client at the bridge.
3. **Point the bridge at a sandbox you own.** The bridge refuses any write outside the path in its
   env file; the demo used `dev.libretexts.org/Sandboxes/<user>`. Clone a public book into it
   first so there is something to scan.
4. **Scan.** Open `/projects/<id>/accessibility` in Conductor, run the page scans, read the matrix.
   The score counts automatic checks only; manual and untested columns are the human backlog.
5. **Preview one targeted fix.** On a page row, open *Fix*, keep only the `duplicate-id` findings,
   *Preview changes*, *Show HTML diff*. Apply is a separate, confirmed step; the demo stops at the
   preview.
6. **Restore page tags with the bridge** (the change behind the demo's `link-name` 82 → 0). Build a
   manifest with `tools/build-biology-tag-manifest.mjs` (or write one for your book — the shape is
   `fixtures/biology-tag-restore.json` in the bridge repo), then:

   ```bash
   docker compose exec remedy-bridge node packages/cli/dist/index.js \
     tags-restore --manifest fixtures/biology-tag-restore.json --dry-run       # per-page diff, no writes
   docker compose exec remedy-bridge node packages/cli/dist/index.js \
     tags-restore --manifest fixtures/biology-tag-restore.json --page <id>    # one-page trial
   ```

   Restore only the tags the failing component reads. On CXone a tag prefix is a site-template
   trigger, not inert metadata: `article:*` pulls in templates that may not exist on the target
   site, `authorname:*` renders an author box with an empty-alt image. `tags-revert
   --snapshot-path` undoes a page from the snapshot the restore took first.
7. **Rescan** and compare. What remains on the demo site is the shared reader skin (header, footer,
   menu contrast and link styling) — outside any sandbox and outside this stack's write guard.

The **Remediation work queue** panel under the matrix (work items with status, owner and scan
evidence) and the **WCAG verification** panel come from patches 0004–0010 of
`conductor-remedy-patch`; applying only 0001–0003 gives the matrix without them.

---

## Naming, because the history is confusing

The same components appear under older names in commit history, code comments,
and a few README snippets that have not caught up:

| You may see | It means |
|---|---|
| `libretexts_remedy`, `libre-remedy` | the **bridge** repo (also the Docker network name — unrelated collision) |
| `libre-remedy-server`, `project_remedy` | the **server** (`project_remedy` is still the live Python import package) |
| `remedy-pdf` | the server's dev CLI entry point |

Public `/v1/*` paths, SQLite identifiers, and the Python import package are
unchanged by any of these renames.

---

## Reverse proxy

`deploy/Caddyfile` (one level up) terminates TLS for **remedy-server** only. In
the LibreTexts.dev reference deployment the public hostname
`remedy.<domain>` points at the **bridge** on `127.0.0.1:8092`, and the server
is not publicly exposed at all — the scanner reaches it over the internal
Docker network. Choose deliberately; exposing `/v1/*` publicly means
`APP_API_KEY` is the only thing in front of the remediation engine.
