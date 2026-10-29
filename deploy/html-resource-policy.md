# Offline HTML rendering and checking

Uploaded and generated HTML use the same offline resource policy for PDF
rendering, visual comparison, axe, pa11y and Lighthouse. The original HTML is
transported from memory at an intercepted synthetic document URL. No directory
server or `file:` navigation is used. Browser contexts, storage and profiles
are fresh; browser and Node environments omit provider credentials, proxy
settings, service keys and custom Node launch flags.

The policy permits inline styles and embedded `data:` images/fonts/styles.
Documents requiring remote resources, arbitrary local files, linked directory
assets, scripts, frames, plugins, a base URL or refresh navigation cannot be
fully evaluated. Their original content is retained; it is not removed to
obtain a pass. A CSP refusal, blocked request, unsupported active construct,
changed navigation or failed tool yields an incomplete evaluation. HTML-to-PDF
publishes no partial PDF. Generated HTML can remain a usable artifact with an
explicit failed/advisory validation result. Neither case certifies the original
document's accessibility or fidelity. Embed required assets in the document
before submission. There is **no external allowlist or bypass setting**.

DNS resolution is disabled for browser document traffic, CSP denies document
scripts/connect/frames/workers/plugins, and request interception denies all
traffic except the one in-memory document. These controls also apply to
loopback, private, metadata, redirect and file destinations. Browser document
code cannot initiate a request to the Bridge or receive its service keys.
API service-to-service forwarding is a separate authenticated operation.

The Node adapter runs pa11y's actual HTML CodeSniffer checks and Lighthouse's
accessibility **snapshot** audits on its already rendered page; it never lets
a CLI start another unprotected browser. Lighthouse's optional full-page
report screenshot is disabled; all selected accessibility audits still run.
The public v1 response envelope, partial-tool failure and false verdicts remain
unchanged. Checker packages and their transitive dependencies are pinned in
`src/project_remedy/html_tools/package-lock.json`; local injected axe and
CodeSniffer bytes are checked against `assets.json`. No CDN is used. The full
image installs these assets with `npm ci --ignore-scripts`. For native local
development, install Node 24.12.0 and run:

```sh
PUPPETEER_SKIP_DOWNLOAD=true npm ci --ignore-scripts --prefix src/project_remedy/html_tools
```

## Supported Linux container policy

Use the full `runtime` image, Linux amd64, a non-root user, reaping init,
`cap_drop: [ALL]`, `no-new-privileges:true`, at least 256 MiB shared memory and
`deploy/chromium-seccomp-amd64.json`. Both Compose examples select that Server
policy. Root and unavailable Chromium sandboxes fail; there is no
`--no-sandbox` wrapper or retry. Native hosts must independently permit the
unprivileged Chromium namespace sandbox. Do not disable seccomp, add
`SYS_ADMIN`, run privileged, or change global kernel/AppArmor policy to make a
test pass. A host that cannot run this profile is unsupported until its owner
provides a reviewed compatible policy.

The seccomp file originates from adapt-a11y-scanner commit
`0f1f9150451e6f6f126c1964c3cc80c8997c2f59`,
`deploy/chromium-seccomp-amd64.json`. Server's LT-170 delta adds only native
amd64 `pidfd_open` with flags zero and `pidfd_send_signal` with null siginfo
and flags zero. The supervisor requires those operations to pin child identity
and signal unreaped children without numeric PID reuse. The original policy
returned EPERM for both, making the strict runtime unavailable. No other
syscall rules or the default ERRNO action change. It retains that reviewed namespace
creation policy and Chromium's chroot-inside-user-namespace allowance; dropped
container capabilities must still deny chroot in the container namespace.
Scanner's evidence is provenance, not Server verification.

The [Linux pidfd_open manual](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
documents the unreaped-child identity guarantee; the
[pidfd_send_signal manual](https://man7.org/linux/man-pages/man2/pidfd_send_signal.2.html)
documents signal permission and PID namespace checks. These allowances grant
no capabilities, do not allow `pidfd_getfd`, and do not bypass those kernel
checks. Full-runtime preflight must establish pidfd access and subreaper
adoption before collecting tests, followed by real descendant/crash/shutdown
tests and all four sandboxed HTML tools in that same image and filter.

Server full-runtime CI runs the actual image as non-root without networking,
using synthetic listeners and documents. A read-only host observer only reads
processes reported by `docker top` for the named test container and matches
their container PID and kernel start time. Each actual renderer/checker launch
must omit sandbox-disabling flags, keep zero effective capabilities and
NoNewPrivs, and have a renderer with additional seccomp filtering and distinct
user/PID namespaces. Evidence and image configuration are uploaded as
`remedy-html-runtime-evidence`. Missing proof fails the job. The observer grants
no extra permissions to the image. Component proof does not establish
assembled-stack deployment, upgrade, rollback or resource-envelope readiness.
