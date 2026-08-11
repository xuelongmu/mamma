"""Canonical pixel-space policy and cross-stage geometry manifests."""
from __future__ import annotations

import hashlib
import json
import os
import warnings
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np

from .calibration import Camera, VALID_DISTORTION_MODELS


DISTORTION_MODES = ("auto", "undistort", "raw")
GEOMETRY_FILENAME = "geometry.json"
PINHOLE_SPACE = "pinhole_undistorted"
RAW_SPACE = "raw_distorted"
UNKNOWN_SPACE = "unknown"
SOURCE_PIXEL_SPACES = (RAW_SPACE, PINHOLE_SPACE, UNKNOWN_SPACE)


def unwrap_scalar(value):
    """Return the Python value stored in a zero-dimensional numpy array."""
    if value is None:
        return None
    if hasattr(value, "shape") and value.shape == ():
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return value


def camera_from_cam_data(cam_data: Mapping) -> Optional[Camera]:
    """Reconstruct the camera contract carried by a per-camera ma_cap NPZ."""
    model = unwrap_scalar(cam_data.get("distortion_model"))
    coeffs = cam_data.get("distortion_coeffs")
    if model is None or coeffs is None:
        legacy = cam_data.get("vicon_radial_2")
        if legacy is not None:
            legacy = np.asarray(legacy)
            if legacy.shape == (5,):
                model, coeffs = "vicon_radial_2", legacy
    if model is None or coeffs is None:
        return None

    K = cam_data.get("cam_int")
    width = unwrap_scalar(cam_data.get("cam_img_w"))
    height = unwrap_scalar(cam_data.get("cam_img_h"))
    if K is None or width is None or height is None:
        return None
    return Camera(
        name=str(unwrap_scalar(cam_data.get("cam_name")) or ""),
        width=int(width),
        height=int(height),
        intrinsics=np.asarray(K, dtype=np.float64).reshape(3, 3),
        distortion_model=str(model),
        distortion_coeffs=tuple(float(v) for v in np.asarray(coeffs).ravel()),
        T_cam_world=np.eye(4, dtype=np.float64),
        T_world_cam=np.eye(4, dtype=np.float64),
    )


def has_nonzero_distortion(camera: Optional[Camera]) -> bool:
    if camera is None:
        return False
    coeffs = tuple(float(v) for v in camera.distortion_coeffs)
    if camera.distortion_model == "vicon_radial_2":
        return len(coeffs) >= 5 and any(v != 0.0 for v in coeffs[2:5])
    return any(v != 0.0 for v in coeffs)


def normalize_source_pixel_space(value) -> str:
    """Validate and normalize the pixel space of the delivered RGB frames."""
    value = unwrap_scalar(value)
    value = UNKNOWN_SPACE if value in (None, "") else str(value).lower()
    if value not in SOURCE_PIXEL_SPACES:
        raise ValueError(
            f"source_pixel_space must be one of {SOURCE_PIXEL_SPACES}, got {value!r}"
        )
    return value


def source_pixel_space_from_cam_data(cam_data: Mapping) -> str:
    """Read the source-space declaration from ma_cap metadata.

    ``pixel_space`` is accepted as the legacy field emitted by the first
    geometry-contract implementation. Missing metadata is deliberately
    ``unknown``: lens coefficients describe a calibration model, not whether
    an exporter has already rectified the delivered frames.
    """
    value = cam_data.get("source_pixel_space")
    if value is None:
        value = cam_data.get("pixel_space")
    return normalize_source_pixel_space(value)


def resolve_distortion_mode(
    mode: str,
    camera: Optional[Camera],
    source_pixel_space: str = UNKNOWN_SPACE,
) -> tuple[bool, str]:
    """Return ``(apply_remap, output_pixel_space)`` for one camera.

    Calibration coefficients and source pixels are independent contracts.
    ``auto`` only remaps a source explicitly declared ``raw_distorted``. A
    non-zero lens model paired with an ``unknown`` source fails rather than
    guessing. ``undistort`` is the explicit override for legacy inputs whose
    raw source space is known operationally but not encoded in metadata.
    """
    mode = str(mode or "auto").lower()
    if mode not in DISTORTION_MODES:
        raise ValueError(
            f"distortion_mode must be one of {DISTORTION_MODES}, got {mode!r}"
        )
    source_pixel_space = normalize_source_pixel_space(source_pixel_space)
    nonzero = has_nonzero_distortion(camera)
    if mode == "raw":
        if source_pixel_space == UNKNOWN_SPACE:
            return False, UNKNOWN_SPACE if nonzero else PINHOLE_SPACE
        if source_pixel_space == RAW_SPACE and not nonzero:
            return False, PINHOLE_SPACE
        return False, source_pixel_space
    if mode == "auto" and source_pixel_space == PINHOLE_SPACE:
        return False, PINHOLE_SPACE
    if mode == "undistort" and source_pixel_space == PINHOLE_SPACE:
        raise ValueError(
            "distortion_mode='undistort' would double-remap a source declared "
            "pinhole_undistorted; use distortion_mode='auto' or 'raw'"
        )
    if camera is None:
        if mode == "undistort":
            raise ValueError("distortion_mode='undistort' requires camera calibration")
        if source_pixel_space == RAW_SPACE:
            raise ValueError(
                "distortion_mode='auto' cannot canonicalize a raw_distorted "
                "source without camera calibration"
            )
        return False, source_pixel_space
    if mode == "auto" and source_pixel_space == UNKNOWN_SPACE and nonzero:
        raise ValueError(
            f"camera {camera.name!r} has non-zero distortion coefficients but "
            "source_pixel_space is unknown. Declare source_pixel_space as "
            f"{RAW_SPACE!r} or {PINHOLE_SPACE!r} in capture metadata, or use "
            "an explicit distortion_mode"
        )
    if camera.distortion_model not in VALID_DISTORTION_MODELS:
        if nonzero:
            raise ValueError(
                f"unsupported distortion model {camera.distortion_model!r} for "
                f"camera {camera.name!r}"
            )
        return False, PINHOLE_SPACE
    return nonzero, PINHOLE_SPACE


def _sha256_array(value) -> str:
    array = np.asarray(value, dtype=np.float64)
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def geometry_record(
    camera: Optional[Camera],
    mode: str,
    *,
    name: str = "",
    source_pixel_space: str = UNKNOWN_SPACE,
) -> dict:
    source_pixel_space = normalize_source_pixel_space(source_pixel_space)
    apply_remap, pixel_space = resolve_distortion_mode(
        mode, camera, source_pixel_space
    )
    if camera is None:
        return {
            "camera": name,
            "source_pixel_space": source_pixel_space,
            "pixel_space": pixel_space,
            "remapped": apply_remap,
            "distortion_model": "none",
            "distortion_coeffs_sha256": _sha256_array([]),
            "projection_intrinsics_sha256": "",
            "width": 0,
            "height": 0,
        }
    return {
        "camera": camera.name or name,
        "source_pixel_space": source_pixel_space,
        "pixel_space": pixel_space,
        "remapped": apply_remap,
        "distortion_model": camera.distortion_model,
        "distortion_coeffs_sha256": _sha256_array(camera.distortion_coeffs),
        "projection_intrinsics_sha256": _sha256_array(camera.intrinsics),
        "width": int(camera.width),
        "height": int(camera.height),
    }


def geometry_record_from_cam_data(cam_data: Mapping, mode: str) -> dict:
    camera = cam_data.get("_distortion_camera") or cam_data.get("_undistort_camera")
    if camera is None:
        camera = camera_from_cam_data(cam_data)
    name = str(unwrap_scalar(cam_data.get("cam_name")) or "")
    source_pixel_space = source_pixel_space_from_cam_data(cam_data)
    return geometry_record(
        camera, mode, name=name, source_pixel_space=source_pixel_space
    )


def write_geometry_manifest(output_dir, stage: str, records: Iterable[dict]) -> Path:
    path = Path(output_dir) / GEOMETRY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    by_camera = {record["camera"]: record for record in records}
    payload = {"schema_version": 2, "stage": stage, "cameras": by_camera}
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)
    return path


def load_geometry_manifest(directory) -> Optional[dict]:
    path = Path(directory) / GEOMETRY_FILENAME
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") not in (1, 2) or not isinstance(payload.get("cameras"), dict):
        raise ValueError(f"invalid geometry manifest: {path}")
    return payload


_MATCH_FIELDS = (
    "source_pixel_space",
    "pixel_space",
    "distortion_model",
    "distortion_coeffs_sha256",
    "projection_intrinsics_sha256",
    "width",
    "height",
)


def validate_geometry_manifest(upstream_dir, records: Iterable[dict], consumer: str) -> bool:
    """Reject an existing upstream manifest that disagrees with current inputs."""
    manifest = load_geometry_manifest(upstream_dir)
    if manifest is None:
        warnings.warn(
            f"{consumer}: no {GEOMETRY_FILENAME} in {upstream_dir}; "
            "accepting legacy artifacts without geometry verification",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    expected = {record["camera"]: record for record in records}
    mismatches = []
    for name, record in expected.items():
        previous = manifest["cameras"].get(name)
        if previous is None:
            mismatches.append(f"{name}: missing upstream camera")
            continue
        for field in _MATCH_FIELDS:
            if previous.get(field) != record.get(field):
                mismatches.append(
                    f"{name}.{field}: upstream={previous.get(field)!r}, "
                    f"current={record.get(field)!r}"
                )
    if mismatches:
        raise ValueError(
            f"{consumer}: incompatible cached pixel geometry in {upstream_dir}:\n  - "
            + "\n  - ".join(mismatches)
        )
    return True


def require_pinhole_optimizer_geometry(prediction_dir) -> bool:
    """Reject raw-distorted 2D observations before pinhole-only fitting."""
    manifest = load_geometry_manifest(prediction_dir)
    if manifest is None:
        warnings.warn(
            f"ma_3d: no {GEOMETRY_FILENAME} in {prediction_dir}; accepting legacy "
            "2D predictions without pixel-space verification",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    bad = [
        name for name, record in manifest["cameras"].items()
        if record.get("pixel_space") != PINHOLE_SPACE
    ]
    if bad:
        raise ValueError(
            "ma_3d uses a pinhole projector and can only consume "
            f"{PINHOLE_SPACE!r} 2D observations. Declare the RGB source pixel "
            "space and re-run ma_masks and ma_2d with distortion_mode=auto, "
            f"or use explicit undistort for known raw inputs. Cameras: "
            f"{', '.join(sorted(bad))}"
        )
    return True
