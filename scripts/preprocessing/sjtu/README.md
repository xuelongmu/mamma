# SJTU sports adapter

`prepare_sjtu_for_mamma.py` conforms one synchronized SJTU multi-view sports
clip for MAMMA. It re-encodes the selected cameras to a common frame rate and
writes `calibration.json`, `capture.json`, and an auditable
`conformance.json` manifest.

The adapter converts the documented calibration convention
`Xc = R * (Xw - C)` into the MAMMA world-to-camera convention
`[R | -R*C_metres]`. Metric scale is inferred from adjacent camera spacing;
that assumption must be checked for each newly downloaded dataset version.

See [`docs/sjtu-sports.md`](../../../docs/sjtu-sports.md) for commands,
camera subsets, validation, and the X-up visualization requirement.
