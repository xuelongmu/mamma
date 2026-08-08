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


def resolve_distortion_mode(mode: str, camera: Optional[Camera]) -> tuple[bool, str]:
    """Return ``(apply_remap, output_pixel_space)`` for one camera."""
    mode = str(mode or "auto").lower()
    if mode not in DISTORTION_MODES:
        raise ValueError(
            f"distortion_mode must be one of {DISTORTION_MODES}, got {mode!r}"
        )
    nonzero = has_nonzero_distortion(camera)
    if mode == "raw":
        return False, RAW_SPACE if nonzero else PINHOLE_SPACE
    if camera is None:
        if mode == "undistort":
            raise ValueError("distortion_mode='undistort' requires camera calibration")
        return False, PINHOLE_SPACE
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


def geometry_record(camera: Optional[Camera], mode: str, *, name: str = "") -> dict:
    apply_remap, pixel_space = resolve_distortion_mode(mode, camera)
    if camera is None:
        return {
            "camera": name,
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
    return geometry_record(camera, mode, name=name)


def write_geometry_manifest(output_dir, stage: str, records: Iterable[dict]) -> Path:
    path = Path(output_dir) / GEOMETRY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    by_camera = {record["camera"]: record for record in records}
    payload = {"schema_version": 1, "stage": stage, "cameras": by_camera}
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
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cameras"), dict):
        raise ValueError(f"invalid geometry manifest: {path}")
    return payload


_MATCH_FIELDS = (
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
            "ma_3d uses a pinhole projector and cannot consume raw-distorted "
            f"2D observations. Re-run ma_masks and ma_2d with "
            f"distortion_mode=auto or undistort. Cameras: {', '.join(sorted(bad))}"
        )
    return True
