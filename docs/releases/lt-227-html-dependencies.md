# LT227: supported HTML dependency maintenance

The HTML tooling remains axe-core4.12.0, pa11y10.0.0 and Lighthouse13.6.0.
Their public checker/JSON interfaces, browser versions, byte/time/resource policy,
seccomp, ownership and credentials-free offline operation are unchanged.

## Supported dependency path

[Sentry11.11.0](https://github.com/getsentry/sentry-javascript/releases/tag/11.11.0)
published November5,2026 includes maintainer change26014. Lighthouse13.6.0
already permits `@sentry/node ^11.8.0`. The supported update selects:

```text
Lighthouse13.6.0
  @sentry/node11.11.0
    @sentry/bundler-plugins11.11.0
      glob14.0.4 (parent range ^14.0.3)
        minimatch11.0.5 (parent range ^11.0.5)
```

The old glob13.0.6/minimatch10.2.6 lock was affected by
[GHSA-3g3m-2fjr-6pw4](https://github.com/advisories/GHSA-3g3m-2fjr-6pw4) and
[GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249).
The November2 audit reported five propagated moderate entries; the November5
baseline audit reports four as registry advisory propagation changed. Both are
retained historical observations; neither is suppressed.

The normal `npm update @sentry/node --package-lock-only --ignore-scripts
--omit=dev --engine-strict` operation changes eleven related entries: Sentry's
exact-version family/conventions, glob, minimatch, path-scurry and its new small
matching helper. package.json and the three direct dependencies remain unchanged.
There is no direct dependency added to force resolution, major override,
downgrade, audit-force or advisory ignore.

## Verification and limits

Clean engine-strict production installs of this exact lock succeeded locally
under Node22.20.0 and24.12.0, with zero audit findings. The installed public-API
probe verifies pinned checker asset integrity, a finite ordinary glob walk,
ordinary minimatch results, rejection of an aborted walk and successful later
work. It creates only three synthetic files in its exact owned temporary path;
there is no exploit payload or unbounded filesystem traversal.

CI repeats those installations, installed-graph records, audits and bounded API
probe on both Node versions. The shipping full-runtime job separately runs real
axe/pa11y/Lighthouse and HTML rendering/HTTP/resource-policy tests, including actual
Chromium namespace/security identity and deadline/cancellation ownership checks.
Matrix installation/API success alone does not establish Linux browser support;
that claim depends on the matching shipping receipts. Python's deployed lock is
audited independently. CI/PR records carry the exact source-specific outcomes.

Node24.12.0 remains the shipping Dockerfile default. No Python lock, browser/native
binary pin, base-selection mechanism, HTML asset manifest or sandbox policy is
changed by this maintenance. Resolved bases and native/browser identities belong
to the actual runtime/candidate receipts; unchanged source pins are not fresh
execution evidence.

## Integration handoff

The retained original20a LT197 archive is byte-preserved historical provenance.
Its old pypdf6.21.2/runtime lock is not repaired by this source change. A current
compatible package must combine this reviewed repair with the accepted producer
records and NEW matching archive/import/TLS/public-profile/recovery/cold-operation
proof. PR19 remains a separate draft until those gates are complete.

One maintained full integration retains optional review-only rollout. LibreTexts
owns deployment timing, actual host/provider/SSO acceptance and vendor-supported
conditional-write/adapter/target-policy validation. Keys alone never enable
production writes. All global acceptance/write flags remain false pending the
release owner's review; this dependency repair is not deployment approval.
