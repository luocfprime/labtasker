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

## Write consistent release notes

Summarize user-visible changes since the immediately previous published release.
Do not describe internal refactors, tests or CI maintenance as product changes,
and do not promise compatibility that the specification does not provide. Use
short imperative-present bullets such as `Add`, `Change` and `Fix`, name the
affected Client, Server, CLI or Worker when that distinction matters, and combine
closely related commits into one outcome. End every bullet with a period and
order bullets by user impact, with compatibility and behavior changes before
additions and fixes. Use `vVERSION` as the GitHub Release title.

Use this shape for every GitHub Release. The compatibility notice is conditional,
and the comparison line is omitted only for the repository's first release:

```markdown
> [!IMPORTANT]
> This release changes Client-Server compatibility. Upgrade the Server to
> vVERSION first, then upgrade all Clients and Workers to vVERSION. Earlier
> Clients cannot [...exact consequence...].

## Changes

- Add ...
- Change ...
- Fix ...

**Full Changelog**: [vPREVIOUS...vVERSION](https://github.com/luocfprime/labtasker/compare/vPREVIOUS...vVERSION)
```

Put a GitHub `[!IMPORTANT]` admonition before `## Changes` when a release changes
Client-Server interoperability, supported version combinations, API or persisted
database compatibility, or requires an upgrade or migration action. State the
exact consequence and action instead of writing only “compatibility changes.”
Cover, when applicable:

- whether upgrading both Client and Server is required or only recommended;
- which mixed-version combinations remain supported;
- the required upgrade order;
- whether database migration is automatic or requires a manual step; and
- what fails or becomes unavailable if versions are mixed.

Use `required` only when mixed versions are unsupported or unsafe. If the current
and previous v2 Clients remain supported by the new Server, say that explicitly
and use `recommended` for a same-version upgrade. Do not add an admonition when
there is no compatibility or upgrade information worth calling out; repeated
empty warnings make real warnings less visible.

For a compatible release that merely benefits from matching versions, use this
form rather than implying that a coordinated upgrade is mandatory:

```markdown
> [!IMPORTANT]
> This release includes Server changes. Upgrading the Client and Server together
> is recommended. Existing v2 Clients remain compatible.
```

For an incompatible release, use `required`, give the supported versions and
upgrade order, and state any migration behavior in the same notice. Do not use
vague notices such as “Server changes” without telling the reader what to do.

Keep the `Full Changelog` comparison as the final line even when GitHub generated
it automatically. Compare the immediately previous published release tag with
the new tag, including across a major-version boundary, and use the visible
`vPREVIOUS...vVERSION` label. Do not replace the curated summary with the commit
comparison and do not add a comparison link when no previous release exists.
Keep the single `## Changes` heading for ordinary releases rather than switching
between `Highlights`, `What's Changed`, `Bug fixes` and generated commit groups.

## Publish only with explicit authorization

Immediately before any tag, push, GitHub Release, or PyPI operation, recheck the
exact commit, clean-worktree state, version alignment, artifact contents, and
authorization. Use an annotated `vVERSION` tag unless the repository establishes
a different convention.

The reviewed `.github/workflows/release.yml` workflow publishes all three
distributions when a GitHub Release is published. It requires a `vVERSION` tag,
the ordinary and real distributed gates for the exact commit, clean-wheel smoke
tests, and protected `pypi`, `pypi-client`, and `pypi-server` environments. PyPI
must register that workflow with environment `pypi-client` for
`labtasker-client`, `pypi-server` for `labtasker-server`, and `pypi` for
`labtasker`. Do not add a manual publishing trigger, improvise credentials, or
copy the v1 single-package workflow.
