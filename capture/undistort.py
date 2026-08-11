"""Frame undistortion for the inference pipeline.

Supported models:

* ``radtan`` / ``opencv_brown`` use OpenCV Brown-Conrady coefficients and
  are rectified into the original camera matrix ``K``.
* ``vicon_radial_2`` uses Vicon's pixel-space radial model.

The Vicon distortion model is **not** OpenCV-compatible: it applies a
radial correction in raw pixel-space coordinates rather than in
normalized image coords. The math here is ported verbatim from
``capture-hall-toolkit/cameras/utils.py`` (``radial_distortion_correction``
+ ``undistort_image_custom``). See that file for the original Vicon
reference math.

Coefficient layout (matches :data:`capture.calibration.VALID_DISTORTION_MODELS`
entry ``"vicon_radial_2"``)::

    [pp_x, pp_y, rad_1, rad_2, rad_3]

The scale factor applied to ``(x - pp_x, y - pp_y)`` is::

    1 + rad_1 * d^2 + rad_2 * d^4 + rad_3 * d^6      where d^2 = (x-pp_x)^2 + (y-pp_y)^2

This module memoizes the ``(map_x, map_y)`` arrays per camera so the
3M-point meshgrid is built once per (camera, resolution) and reused for
every frame — important when processing 1000+ frames × 30+ cameras.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

import numpy as np

from .calibration import Camera


_CACHE: Dict[tuple, Tuple[np.ndarray, np.ndarray]] = {}
_CACHE_LOCK = threading.Lock()


def _radial_correction(
    x: np.ndarray, y: np.ndarray,
    pp_x: float, pp_y: float,
    rad_1: float, rad_2: float, rad_3: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Vicon radial correction in pixel space (see module docstring)."""
    cx = x - pp_x
    cy = y - pp_y
    d_sq = cx * cx + cy * cy
    scale = 1.0 + rad_1 * d_sq + rad_2 * d_sq ** 2 + rad_3 * d_sq ** 3
    return cx * scale + pp_x, cy * scale + pp_y


def _build_maps(camera: Camera) -> Tuple[np.ndarray, np.ndarray]:
    """Build ``cv2.remap`` maps into the canonical pinhole ``K`` frame."""
    w, h = int(camera.width), int(camera.height)
    if camera.distortion_model == "vicon_radial_2":
        pp_x, pp_y, rad_1, rad_2, rad_3 = camera.distortion_coeffs[:5]
        x_coords, y_coords = np.meshgrid(np.arange(w), np.arange(h))
        map_x_flat, map_y_flat = _radial_correction(
            x_coords.flatten().astype(np.float64),
            y_coords.flatten().astype(np.float64),
            float(pp_x), float(pp_y),
            float(rad_1), float(rad_2), float(rad_3),
        )
        return (
            map_x_flat.reshape(h, w).astype(np.float32),
            map_y_flat.reshape(h, w).astype(np.float32),
        )

    import cv2

    K = np.asarray(camera.intrinsics, dtype=np.float64).reshape(3, 3)
    dist = np.asarray(camera.distortion_coeffs, dtype=np.float64)
    return cv2.initUndistortRectifyMap(
        K, dist, None, K, (w, h), cv2.CV_32FC1
    )


def _is_noop(camera: Optional[Camera]) -> bool:
    """True if undistortion would be the identity or is unsupported."""
    if camera is None:
        return True
    coeffs = tuple(float(v) for v in (camera.distortion_coeffs or ()))
    if camera.distortion_model == "vicon_radial_2":
        if len(coeffs) < 5:
            return True
        return all(v == 0.0 for v in coeffs[2:5])
    if camera.distortion_model in ("radtan", "opencv_brown"):
        if len(coeffs) < 4:
            return True
        return all(v == 0.0 for v in coeffs)
    return True


def get_maps(camera: Camera) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Return cached (map_x, map_y) for ``camera``, or ``None`` if no-op."""
    if _is_noop(camera):
        return None
    key = (
        camera.name,
        camera.distortion_model,
        int(camera.width),
        int(camera.height),
        tuple(float(v) for v in camera.distortion_coeffs),
        tuple(np.asarray(camera.intrinsics, dtype=np.float64).ravel()),
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        maps = _build_maps(camera)
        _CACHE[key] = maps
    return maps


def undistort_rgb(image: np.ndarray, camera: Optional[Camera]) -> np.ndarray:
    """Return ``image`` undistorted via ``camera``'s coeffs (or unchanged).

    No-op when ``camera`` is ``None`` or the coefficients are all zero.
    Maps are built lazily on first call per camera and cached thereafter.
    """
    maps = get_maps(camera) if camera is not None else None
    if maps is None:
        return image
    import cv2
    map_x, map_y = maps
    return cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR)
