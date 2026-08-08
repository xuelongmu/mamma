# Changelog

All notable repository changes are recorded here. Experimental outcomes and
machine-local progress belong in [`docs/status.md`](docs/status.md).

## Unreleased

### Added

- Agent and contributor guidance for research logging, pull requests, and
  functionally dependent stacked pull requests.
- An explicit safeguard that issues and pull requests must target the fork,
  never the upstream repository.
- A gitignored repository-local `tmp/` scratch area and a prohibition on
  committing or uploading media assets through repository hosting.
- A dated research log in `docs/status.md`.
- Local operations, Rerun viewer, and SJTU sports runbooks.
- A reusable SJTU sports calibration and footage adapter.
- A share-video renderer with upright, Rerun-style presentation and a
  synchronized camera filmstrip.
- Camera-count ablation captures and helper commands.

### Changed

- Expanded own-footage guidance for synchronization, camera coverage,
  calibration conventions, and the released iPhone example.
- Rerun visualization now records the configured world up axis at the scene
  root.

### Fixed

- X-up and Y-up reconstructions no longer appear sideways in Rerun when the
  corresponding visualization up-axis option is used.
