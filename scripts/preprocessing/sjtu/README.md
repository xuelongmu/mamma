# SJTU sports adapter

`prepare_sjtu_for_mamma.py` conforms one synchronized SJTU multi-view sports
clip for MAMMA. It re-encodes the selected cameras to a common frame rate and
writes `calibration.json`, `capture.json`, and an auditable
`conformance.json` manifest.

Completed camera videos are reused when resuming. New encodes are written to a
temporary sibling and atomically renamed only after ffmpeg succeeds;
`--overwrite` intentionally recomputes every selected camera. Generated
capture paths are relative to `capture.json` so the conformed session can move
with its parent directory.

Reuse is allowed only when the existing conformance manifest matches the
source root, clip interval, frame rate, and physical camera-spacing assumption.
Use a new session or pass `--overwrite` when any of those inputs change.

The adapter converts the documented calibration convention
`Xc = R * (Xw - C)` into the MAMMA world-to-camera convention
`[R | -R*C_metres]`. Metric scale is inferred from adjacent camera spacing;
that assumption must be checked for each newly downloaded dataset version.

See [`docs/sjtu-sports.md`](../../../docs/sjtu-sports.md) for commands,
camera subsets, validation, and the X-up visualization requirement.
