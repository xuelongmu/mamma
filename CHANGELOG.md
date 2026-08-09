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
- A validated Depthkit/Scatter calibration and RGB adapter with nested
  4/6/8-view quick/full experiment presets.
- A share-video renderer with upright, Rerun-style presentation and a
  synchronized camera filmstrip.
- Depthkit-aware share rendering with Y-down world conversion, optional
  opposite-side 3D views, and landmark-based suppression of unconstrained
  entrance and exit meshes.
- Camera-count ablation captures and helper commands.
- A quantitative MammaEval 4/6/8-view research entry with camera-quality and
  ground-truth provenance caveats.
- Cross-platform internal Rerun handoff instructions for Windows, Linux/WSL,
  and macOS.

### Changed

- Expanded own-footage guidance for synchronization, camera coverage,
  calibration conventions, and the released iPhone example.
- Rerun visualization now records the configured world up axis at the scene
  root.

### Fixed

- X-up and Y-up reconstructions no longer appear sideways in Rerun when the
  corresponding visualization up-axis option is used.
- Y-down reconstructions can select `--up-axis y-down` for signed floor detection,
  ground normals, and Rerun world-coordinate metadata.
- Share-video filmstrips can preserve the source-frame offset for sliced
  reconstructions.
- SJTU visualization uses the conformed 25 fps timeline, and the adapter now
  rejects unsupported fractional rates instead of allowing downstream drift.
- SJTU conformance checks all source and destination paths before encoding.
- SJTU conformance resumes completed cameras, atomically publishes new encodes,
  and writes portable session-relative capture paths.
- Share-video rendering now fails with camera and frame context when a source
  stream cannot supply a requested filmstrip frame.
- Resume rejects conformed videos whose source or encode settings do not match
  the recorded manifest, and physical camera spacing must be finite and
  positive.
- SJTU mask videos and collages now use the capture's documented 25 fps rate.
- Conformance manifests track completion per camera so an interrupted
  overwrite cannot reuse stale final-path videos.
- SJTU conformance rejects nested session names, invalid clip intervals,
  non-finite or non-rigid calibration values, nonpositive focal lengths, and
  duplicate camera blocks or nonpositive image sizes before starting an encode.
- Resume compatibility includes the source camera files and calibration
  fingerprint, and published capture descriptors are invalidated during
  incomplete conformance runs.
- Share-video excerpts fit framing to their requested mesh interval and reject
  invalid render rates or source cameras with mismatched frame rates.
- The camera-count ablation helper enters the `mamma` environment and runs the
  environment doctor before starting any pipeline job.
- SJTU conformance verifies that every output stream has a positive, consistent
  frame count, satisfies the requested clip duration, and matches its camera's
  calibrated pixel dimensions before publication.
- Reuse-only conformance preserves verified published descriptors, and camera
  selections reject duplicate IDs before creating a session.
- Share-video rendering verifies that nonzero source-frame seeks were honored
  before emitting synchronized filmstrip frames.
- Depthkit validation now checks converted camera models, rejects degenerate
  rigs and unsafe recording names, and uses an explicit recording-selection
  option.
- Depthkit auto mode reuses only probed H.264/yuv420p integral-CFR streams;
  overwrite and calibration-only reuse cannot leave stale or mismatched
  published descriptors.
- Depthkit calibration-only reuse verifies the source project, calibration,
  recordings, cameras, and video fingerprints before retaining existing pixels.
- Depthkit conversion rejects reported dropped frames and unsupported nonzero
  distortion tails before publishing a frame-index-aligned capture.
- Visualization derives its FPS from the bound capture unless explicitly
  overridden, so non-30-fps captures keep the correct playback speed.
- Masked-output and collage diagnostics also derive FPS from the bound capture.
- Low camera look-at scores warn instead of rejecting valid parallel arrays;
  degenerate coincident-center rigs remain invalid.
- Share-video visibility gating tracks each reconstructed body independently.
- Share-video camera selections reject duplicate names before visibility counts.
