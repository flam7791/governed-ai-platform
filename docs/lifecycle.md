# Lifecycle: versions, releases, upgrades

How the components and the platform change over time without surprises.

## Versions

- Each component follows [semantic versioning](https://semver.org) and keeps a CHANGELOG. A new
  minor version adds features without breaking existing configuration; a major version may.
- A component release is a git tag (`v0.2.0`) on a commit whose CI passed.
- The platform pins the exact tag of every component in `components.env`. A platform release is
  a set of component versions that passed the smoke test together.

## Release checklist for a component

1. CI green: lint, tests on Python 3.10 to 3.13, container build and checks.
2. Evaluation gates pass:
   - gateway: routing evaluation replayed, no regression in pass rate or cost;
   - evidence server: retrieval hit@3 at or above 0.8 and **zero leaks**, keyword and hybrid;
   - agents: trajectory evaluation replayed, **every safety check** passing.
3. CHANGELOG updated; version bumped in `pyproject.toml` and `__init__.py`.
4. Tag and push: `git tag v0.3.0 && git push origin v0.3.0`.

## Upgrading the platform

1. Change the tag in `components.env` in a pull request.
2. CI builds the stack with the new version and runs the smoke test.
3. Merge when green. Deploy by pulling the new images and `docker compose up -d`.
4. **Rollback:** revert the pull request and redeploy. State is compatible across minor
   versions; a major version says in its CHANGELOG if data needs migrating.

## Changing a model

A model change is a release, not a configuration tweak:

- **Chat models:** re-run the gateway's routing evaluation and the agents' trajectory
  evaluation with the new model, record them, compare quality and cost, then switch.
- **Embedding models:** vectors from different models cannot be compared, so the document
  index is rebuilt (`docker compose restart evidence-mcp` re-indexes at start). The evidence
  server refuses to mix models and falls back to keywords until the index matches.
- **Retiring a model:** move traffic first (tier mapping in `config/gateway.json`), watch the
  gateway metrics for requests still naming the old alias, then remove it.

## Prompts and agent instructions

Agent instructions live in each scenario's `scenario.json` and are versioned with the code.
Changing them means re-recording the trajectory evaluation: a different prompt is a different
system, and the safety checks must pass again before release.

## Dependencies and base images

- The weekly CI run rebuilds everything from scratch and catches breaking upstream changes.
- Third-party images (Prometheus) are pinned to a version; update them deliberately.
- Python dependencies have lower bounds and, where an API changed in the past, upper bounds.
