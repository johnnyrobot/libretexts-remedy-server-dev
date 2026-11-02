# Retained original LT197 delivery

This is the original accepted engineering package from source
`20a09894895d8c5df69a6d2c2bb1adbbe08f22c2`, producing run
[41101217910, attempt 1](https://github.com/johnnyrobot/libretexts-remedy-server-dev/actions/runs/41101217910/attempts/1),
artifact `13000643105`. It preserves the original LT197 source, both compiled
Conductor targets, images, metadata and matching receipts. It is not a refreshed
bundle or new runtime proof. Production acceptance and all five global flags
remain false.

The original source locks pypdf 6.21.2, which has the known security findings
documented in the [LT220 repair](../../docs/releases/lt-220-pypdf-security.md).
Current source requires 6.21.4 or newer. Preserve this original for historical
provenance; do not use it as a recommendation for new deployment. Patched images
and a refreshed compatible package need their own matching Linux/runtime and
assembled operational acceptance. Joining the original bytes cannot transfer
old receipts to a new runtime or clear current release gates.

The [versioned retained release](https://github.com/johnnyrobot/libretexts-remedy-server-dev/releases/tag/lt197-original-20a0989-retained-v1)
holds three ordered byte parts of the **original GitHub ZIP**, because that ZIP
exceeds the per-asset size limit. Joining them does not recompress or rebuild it.
Release assets have no scheduled Actions retention expiry. Hash pins detect
replacement; they do not prevent deletion or guarantee hosting availability.
Keep an independent complete offline copy under the release owner's policy.
These hashes are integrity checks, not signatures or independent authenticity;
the reviewed source and original producing run remain the trust prerequisite.

The [retention record](lt197-retention.json) records original acquisition metadata
checked before expiry, original artifact identifiers/digests, ordered part hashes,
original seal hashes and original sealing time. Original Conductor downloads
expire November 12, 2026; the original whole handoff download expires November 29.
Those timestamps remain unchanged. This retained copy uses the existing sealed
offline import path. It never waives the original expiry check for **new** seals.

| Object | SHA256 |
|---|---|
| Retention record | `badb334805a39235196bf6fd6ac49e0ef96f1fb86220b1ed1f47acd5c6bb1f0c` |
| Original GitHub ZIP, 2920270389 bytes | `41522f5132424382e7f701d1f9673536ab7f9ee24c0ac53bb43660df5d1089f9` |
| Original package.tar | `0947538989965cd649dfc6f96f3b0e380271608f5d53113beb4475112f850d51` |
| Original manifest.json | `87800b97582203f28447a8eec7df47df6d86d6562bd3878a3a05ab5c580a266e` |
| Original checksums.sha256 | `8806c99fc0433452e4dfb6b480b5b4ec6b11cd36d8d7c4161f0fc9f89605c47b` |

## Download and restore original bytes

From a reviewed checkout containing this guide, use Python 3.11+ on Linux or
macOS and the GitHub CLI. No new key is needed for the public release. Choose a
new private local directory, with at least 6 GiB free for parts plus the ZIP;
unpacking the whole handoff needs additional space. Existing output paths refuse.

```sh
set -eu
umask 077
mkdir -m 0700 lt197-retained-download
gh release download lt197-original-20a0989-retained-v1 \
  --repo johnnyrobot/libretexts-remedy-server-dev \
  --pattern 'lt197-*' --dir lt197-retained-download
python3 deploy/stack/retained_handoff.py \
  --record lt197-retained-download/lt197-retention.json \
  --record-sha256 badb334805a39235196bf6fd6ac49e0ef96f1fb86220b1ed1f47acd5c6bb1f0c \
  --parts lt197-retained-download --output lt197-original-restored
```

The command verifies the independently pinned record, bounded ordered part sizes
and hashes, and the whole ZIP hash before publishing
`lt197-original-restored/handoff.zip`. It does not extract or execute anything.
It preserves `handoff.zip.partial` as a hard link to the completed ZIP (no second
copy of the bytes). On refusal, only incomplete private output may exist; preserve
it for diagnosis and retry with a new directory. Do not treat partial output as a
verified ZIP. Missing/corrupt assets require another exact retained copy; never
substitute a rebuilt archive or change the trusted hash to match a download.

Continue with [original handoff verification and supported Linux import](integration-profile.md#retaining-and-checking-the-handoff):
check the external seal, TAR, internal/external manifests and every payload hash
before extraction/import, then run the original image/import verifier against
actual loaded identities. Use the original package's `source.tar` and exact
source for runtime/import operations; this retention helper's newer checkout is
not a replacement runtime pin. Original receipts describe the previous matching
Linux proof only. Actual host, storage/network, providers, SSO, vendor atomicity,
release-owner acceptance and live deployment remain separate gates. Scanner and
Mongo still require their original digest-pinned registry pulls.

## New deliveries

A refreshed full package requires reviewed producer source/index records,
both actually compiled Node22 Conductor target candidates and reviewed Bridge
source, synchronized exact consumer pins, and new complete matching assembled
Linux/import/preflight/cold restore/upgrade/rollback/signed synthetic evidence.
Retaining old bytes grants none of that evidence to a new source or package.
