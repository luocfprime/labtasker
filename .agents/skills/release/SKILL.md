---
name: release
description: Prepare, validate, tag, or publish a Labtasker release. Use for version bumps, release readiness, release artifacts, tags, GitHub releases, or PyPI publication; do not use for ordinary development builds.
---

# Release Labtasker

Treat the Client and Server as independently installed distributions that always
ship with one shared version. Separate release preparation from externally
visible publication.

## Establish scope and authority

Determine the requested target version and whether the user asked only to
prepare, or explicitly authorized tagging, pushing, creating a GitHub release,
or publishing to PyPI. Do not infer authorization for later stages.

Inspect the current branch, tags, remotes, `git status`, and all pending diffs.
Do not include unrelated worktree changes in release commits or artifacts. Never
reuse the v1 worktree's release scripts or workflow for v2.

## Prepare the version

Use the deterministic helper from the repository root:

```bash
uv run python .agents/skills/release/scripts/set_version.py VERSION
uv lock
uv run python .agents/skills/release/scripts/set_version.py --check VERSION
```

The helper updates the workspace version, both distribution metadata files, both
public `__version__` values, and the Claude Code plugin/marketplace version. It
maps a PEP 440 prerelease such as `2.1.0rc1` to the corresponding plugin SemVer
`2.1.0-rc.1`. `uv lock` owns lockfile updates. Review the resulting diff and
update user documentation only when the release changes documented behavior. Do
not create a version-only changelog file when the repository has no maintained
changelog.

## Validate release readiness

Run the complete ordinary gate from `AGENTS.md`. Build artifacts only from the
exact reviewed source tree. Then smoke-test the release wheels in clean virtual
environments, confirming that:

- `labtasker-client` imports `labtasker` and provides its CLI without Server
  dependencies;
- `labtasker-server` imports and provides its CLI without the Client package;
- the `labtasker` convenience metapackage installs matching Client and Server
  distributions and both CLIs;
- installed metadata and `__version__` equal the target version; and
- all three source distributions and all three wheels are present.

For a fully release-gated Linux release, also require the distributed integration
suite for the exact commit, either locally with PyTorch and Accelerate installed
or through the repository's distributed CI. Report that gate as pending rather
than pretending it passed when it cannot be verified.

Summarize release notes from user-visible changes since the previous version tag.
Do not describe internal refactors as features and do not promise compatibility
that the specification does not provide.

## Publish only with explicit authorization

Immediately before any tag, push, GitHub Release, or PyPI operation, recheck the
exact commit, clean-worktree state, version alignment, artifact contents, and
authorization. Use an annotated `vVERSION` tag unless the repository establishes
a different convention.

The reviewed `.github/workflows/release.yml` workflow publishes all three
distributions when a GitHub Release is published. It requires a `vVERSION` tag,
the ordinary and real distributed gates for the exact commit, clean-wheel smoke
tests, and a protected `pypi` environment. PyPI must register that workflow and
environment as a Trusted Publisher for `labtasker`, `labtasker-client`, and
`labtasker-server`. Do not add a manual publishing trigger, improvise credentials,
or copy the v1 single-package workflow.
