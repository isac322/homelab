# Immich machine-learning (RKNN) with shared NPU weights

Automated rebuild of the [Immich](https://github.com/immich-app/immich)
`prod-rknn` machine-learning image with
[immich-app/immich#23958](https://github.com/immich-app/immich/pull/23958)
("perf: RKNN half RAM model usage + no weight duplication in multi-core")
applied on top. The PR is still open upstream.

The PR keeps model weights in shared memory across RKNN threads, so
`MACHINE_LEARNING_RKNN_THREADS >= 2` no longer multiplies NPU memory usage.
On rk3588 boards this allows more threads without hitting the ~4 GiB IOMMU
IOVA cap.

## Output

* Image: `ghcr.io/isac322/immich-machine-learning:<immich_tag>-rknn`
  (deployed by [`values/immich/backbone.yaml`](../../values/immich/backbone.yaml))
* Tag policy: identical to upstream
  `ghcr.io/immich-app/immich-machine-learning:<immich_tag>-rknn`
* Arch: `linux/arm64` only (rk3588 / rk3576 / rk3568 / rk3566)
* Variant: `prod-rknn` only (`--target prod --build-arg DEVICE=rknn`)
* Build cache: `ghcr.io/isac322/immich-machine-learning:buildcache` — not a
  runtime tag, never deploy it.

## Automation

The [`immich-ml-rknn`](../../.github/workflows/immich-ml-rknn.yaml)
workflow decides whether to build in its `check` job:

1. **Version.** The `workflow_dispatch` input `immich_version`, or the
   latest stable Immich release (`releases/latest`, must be `vX.Y.Z`).
2. **Existence check.** It asks the GHCR registry directly for the
   `<version>-rknn` manifest with an anonymous pull token (the package is
   public):
   * `200` → already published, skip;
   * `404` → build;
   * anything else → the job fails. It never guesses, so a registry or
     network problem cannot trigger a daily rebuild of an existing tag.
3. **Triggers.**
   * daily schedule (04:00 UTC) — picks up new Immich releases;
   * push to `master` touching `tools/immich-ml-rknn/**` or the workflow —
     a refreshed patch immediately retries an unpublished version (an
     already-published tag is still skipped);
   * `workflow_dispatch` — optional `immich_version`, and `force=true`
     rebuilds even when the tag is already published.

All runs share one concurrency group, so two runs never push the same tag
at once.

The `build` job runs on a native `ubuntu-24.04-arm` runner:

1. Shallow-clones `immich-app/immich` at the target tag.
2. Applies every `patches/*.patch` in sorted order (`git apply --check`
   first). If any patch does not apply, the job fails and names the patch;
   nothing is published. Refresh the patch (below) and push.
3. If the patches changed `machine-learning/pyproject.toml` or `uv.lock`,
   regenerates `uv.lock` with the uv version pinned by upstream's
   `machine-learning/Dockerfile` (`COPY --from=ghcr.io/astral-sh/uv:<ver>@…`),
   so the lock format matches the in-image `uv sync`.
4. Builds `machine-learning/Dockerfile` and pushes the image, with the
   registry build cache at `:buildcache`. The job summary shows the image
   reference and digest.

## Patches

| File | Purpose |
|---|---|
| `01-pr-23958-rknn-shared-weights.patch` | Upstream PR #23958 ported onto v3.3.1: native pybind11 pool sharing weights via `rknn_dup_context` (keeps v3.3's custom-string metadata, fp16 outputs, dynamic shapes, `data_format`), drops `rknn-toolkit-lite2`, pins `librknnrt` v2.3.2, and builds the extension in the `prod` stage with chained `&&` and `/opt/venv/bin` on `PATH` (formerly patch 02) |

Paths inside the patches are relative to the Immich repo root
(`a/machine-learning/...`).

### Refreshing a patch on upstream changes

When the workflow fails with "Patch … does not apply to Immich vX.Y.Z":

```bash
TAG=v3.4.0                       # tag that broke the build
PATCHES="$PWD/tools/immich-ml-rknn/patches"   # run from the homelab root
WORK=$(mktemp -d)

git clone https://github.com/immich-app/immich.git "$WORK/immich"
cd "$WORK/immich"
git checkout "$TAG"
git fetch origin pull/23958/head:pr-23958

# Try a 3-way apply of the current patch first.
git apply --3way "$PATCHES/01-pr-23958-rknn-shared-weights.patch"
# If that fails, merge the PR and resolve conflicts under machine-learning/:
#   git reset --hard "$TAG"
#   git merge --no-ff --no-commit pr-23958
git diff --staged "$TAG" > "$PATCHES/01-pr-23958-rknn-shared-weights.patch"

# Verify the whole series on a fresh clone, in order.
git clone --depth 1 --branch "$TAG" https://github.com/immich-app/immich.git "$WORK/verify"
for p in "$PATCHES"/*.patch; do
  git -C "$WORK/verify" apply --check "$p" && git -C "$WORK/verify" apply "$p"
done
```

Commit the refreshed patch and push to `master`; the push trigger rebuilds
the unpublished version.

## One-time setup: GHCR package access

The `immich-machine-learning` package was originally created by
`isac322/immich-machine-learning-rknn`, so this repository's `GITHUB_TOKEN`
cannot push to it until access is granted:

GitHub → Packages → `immich-machine-learning` → Package settings →
**Manage Actions access** → add `isac322/homelab` with the **Write** role.

The package must also stay public; the workflow's existence check uses an
anonymous registry token.
