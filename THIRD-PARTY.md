# Third-party components

Remedy Server assembles a lot of other people's software. Most of it is
permissive. **Three components are not, and one of them applies the moment you
run this as a network service** — read those three before deploying.

**Running most software raises no licensing question; redistributing a built
image does.** AGPL is the exception, and this image contains AGPL software.

---

## Read these three first

### PyMuPDF is AGPL-3.0, and this is a network service

`pymupdf>=1.25.0` is licensed **AGPL-3.0-or-later** (or commercially, from
Artifex). AGPL section 13 is the network clause: if users interact with the
software **over a network**, they must be offered the corresponding source of
the whole work — not only when you ship them a copy.

Remedy Server is an HTTP API. Deploying it publicly triggers that clause.

Three ways out, in the order most projects pick them:

1. **Offer the source.** Fine here — this repository is MIT and can be published
   as-is. This is the simple answer for an open project.
2. **Buy a commercial PyMuPDF licence** from Artifex, if the source cannot be
   offered.
3. **Remove PyMuPDF.** It is used for PDF inspection alongside `pikepdf`
   (MPL-2.0) and `pypdf` (BSD-3-Clause), which are not AGPL. Whether the
   remaining two cover every code path has not been assessed.

### QuestPDF has a revenue threshold

The rendering sidecar (`sidecar/QuestPdfRenderer`) depends on **QuestPDF
2026.2.4** under the **QuestPDF Community MIT License**. That grant is free only
below an annual gross revenue threshold set by the vendor; organisations above
it need a paid Professional or Enterprise licence.

Confirm which side of that line your organisation falls on before deploying.
This is a question about *your* finances, not about this code, and nobody here
can answer it for you.

### veraPDF is GPL, and it is committed to this repository

`verapdf-installer.zip` — **32 MB, veraPDF Greenfield 1.30.1** — is checked into
the repository root. veraPDF is dual-licensed **GPL-3.0-or-later / MPL-2.0+**.

This matters more than the usual build-time dependency: because the installer is
committed, **cloning or forking this repository redistributes veraPDF**, before
any image is built. If you would rather not carry that, delete the zip and fetch
it during the build instead — the `Dockerfile` documents the exact command:

```
curl -fsSLO https://software.verapdf.org/releases/1.30/verapdf-greenfield-1.30.1-installer.zip
```

The zip was committed to avoid transient network failures during builds. That is
a real convenience with a real cost.

---

## What the built image contains

Assembled from six build stages into one runtime image.

| Component | Pinned | License | Stage |
|---|---|---|---|
| [python:3.13-slim-bookworm](https://hub.docker.com/_/python) | `3.13-slim-bookworm` | PSF-2.0 + Debian base, mixed | `base` |
| **veraPDF Greenfield** | `1.30.1` | **GPL-3.0-or-later / MPL-2.0+** | `verapdf` |
| **QuestPDF** (AOT binary) | `2026.2.4` | **QuestPDF Community MIT — revenue-limited** | `questpdf` |
| .NET runtime (statically linked into the AOT binary) | `net9.0` | MIT | `questpdf` |
| [Typst](https://typst.app) | `0.15.0` | Apache-2.0 | `typst` |
| Node.js | `20.17.0` | MIT | `node-tools` |
| **pa11y** | `8` | **LGPL-3.0-only** | `node-tools` |
| Lighthouse | `12` | Apache-2.0 | `node-tools` |
| Chromium (via Playwright) | matches `playwright` | BSD-3-Clause and others | `playwright` |
| Python dependency set | see below | mostly permissive, **one AGPL** | `python-deps` |

### Python runtime dependencies

**AGPL — see above**

- `pymupdf` — AGPL-3.0-or-later or commercial

**Weak copyleft**

- `pikepdf` — MPL-2.0

**Permissive**

`fastapi` (MIT) · `uvicorn[standard]` (BSD-3-Clause) · `python-multipart`
(Apache-2.0) · `pypdf` (BSD-3-Clause) · `python-docx` (MIT) · `python-pptx`
(MIT) · `openpyxl` (MIT) · `beautifulsoup4` (MIT) · `httpx` (BSD-3-Clause) ·
`cryptography` (Apache-2.0 OR BSD-3-Clause) · `defusedxml` (PSF-2.0) · `lxml`
(BSD-3-Clause) · `pillow` (MIT-CMU/HPND) · `playwright` (Apache-2.0) ·
`aiosqlite` (MIT) · `fonttools` (MIT) · `reportlab` (BSD-3-Clause) · `pyyaml`
(MIT) · `python-dotenv` (BSD-3-Clause) · `click` (BSD-3-Clause) ·
`markdown-it-py` (MIT) · `pygments` (BSD-2-Clause) · `rich` (MIT) · `slowapi`
(MIT) · `structlog` (MIT OR Apache-2.0)

Test-only, not in the runtime image: `pytest`, `pytest-asyncio`, `pytest-cov`.

---

## Documents this software produces

Remedy remediates documents you supply. **Their content is yours and is not
covered by this repository's licence** — nothing here grants rights in a PDF you
feed it, and nothing here claims any.

Fonts are a live version of the same point: `faithful_rebuild` embeds and
subsets fonts from the source document via `fonttools`. Font files carry their
own licences, and some forbid embedding or subsetting. That obligation follows
the document, not this software.

---

## Why this repository is MIT

Everything under `src/`, `backend/`, `sidecar/` and `tools/` is original work.
Nothing here contains or modifies GPL or AGPL source — those arrive as separate
packages and binaries at build time.

MIT for the wrapper does not neutralise AGPL for what it imports. The two
questions are independent: this repository's own terms, and what the assembled
image obliges you to do. The three components at the top are the second question.

## Refreshing this file

The table above lists declared constraints, not resolved versions. Before any
public release, regenerate from what actually shipped:

```bash
uv export --frozen --no-dev --no-hashes            # exact resolved Python versions
docker run --rm remedy-server:local /opt/venv/bin/pip list --format=freeze
docker run --rm remedy-server:local dpkg-query -W -f='${Package} ${Version}\n'
docker run --rm remedy-server:local /opt/node/bin/npm ls -g --depth 0
```

`uv.lock` is committed and is the authoritative record of the Python set.
