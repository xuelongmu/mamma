"""Tests for canonical lens handling and cross-stage geometry contracts."""
from __future__ import annotations

import json

import numpy as np
import pytest

from capture.calibration import Camera
from capture.frame_source import frame_source_from_cam_data
from capture.geometry import (
    PINHOLE_SPACE,
    RAW_SPACE,
    camera_from_cam_data,
    geometry_record,
    require_pinhole_optimizer_geometry,
    resolve_distortion_mode,
    validate_geometry_manifest,
    write_geometry_manifest,
)
from capture.run_ma_cap import _write_cam_npz
from capture.undistort import get_maps, undistort_rgb
from inference.steps.base import StepBuilder


K = np.array(
    [[800.0, 0.0, 64.0], [0.0, 810.0, 48.0], [0.0, 0.0, 1.0]],
    dtype=np.float64,
)
EYE = np.eye(4, dtype=np.float64)


def make_camera(model="opencv_brown", coeffs=(0.12, -0.04, 0.001, -0.002, 0.01)):
    return Camera(
        name="cam00",
        width=128,
        height=96,
        intrinsics=K,
        distortion_model=model,
        distortion_coeffs=tuple(coeffs),
        T_cam_world=EYE,
        T_world_cam=EYE,
    )


@pytest.mark.parametrize(
    "model,coeffs",
    [
        ("radtan", (0.1, -0.03, 0.001, 0.002)),
        ("opencv_brown", (0.1, -0.03, 0.001, 0.002, 0.01)),
        ("vicon_radial_2", (64.0, 48.0, 1e-6, -1e-12, 1e-18)),
    ],
)
def test_ma_cap_roundtrips_generic_distortion(tmp_path, model, coeffs):
    path = tmp_path / "cam00.npz"
    _write_cam_npz(
        path,
        cam=make_camera(model, coeffs),
        image_paths=[],
        ioi_seq_dir=tmp_path,
        frames_len=1,
        video_path="dummy.mp4",
    )
    with np.load(path, allow_pickle=True) as data:
        cam_data = {key: data[key] for key in data.files}
    restored = camera_from_cam_data(cam_data)
    assert restored is not None
    assert restored.distortion_model == model
    assert restored.distortion_coeffs == pytest.approx(coeffs)
    assert str(cam_data["pixel_space"]) == "raw_distorted"


def test_opencv_map_matches_distorted_projection():
    cv2 = pytest.importorskip("cv2")
    camera = make_camera()
    map_x, map_y = get_maps(camera)
    pixels = np.array([[5, 7], [64, 48], [120, 88]], dtype=np.int32)
    normalized = np.column_stack(
        (
            (pixels[:, 0] - K[0, 2]) / K[0, 0],
            (pixels[:, 1] - K[1, 2]) / K[1, 1],
            np.ones(len(pixels)),
        )
    )
    projected, _ = cv2.projectPoints(
        normalized,
        np.zeros(3),
        np.zeros(3),
        K,
        np.asarray(camera.distortion_coeffs),
    )
    projected = projected[:, 0, :]
    mapped = np.column_stack((map_x[pixels[:, 1], pixels[:, 0]], map_y[pixels[:, 1], pixels[:, 0]]))
    assert mapped == pytest.approx(projected, abs=1e-4)


def test_auto_frame_source_returns_canonical_pixels(tmp_path):
    pytest.importorskip("cv2")
    from PIL import Image

    image = np.zeros((96, 128, 3), dtype=np.uint8)
    image[:, ::8] = 255
    image[::8, :] = 255
    frame = tmp_path / "000000.png"
    Image.fromarray(image).save(frame)
    camera = make_camera(coeffs=(0.6, -0.1, 0.0, 0.0, 0.0))
    cam_data = {
        "cam_name": np.array(camera.name),
        "img_abs_path": np.array([str(frame)]),
        "cam_int": camera.intrinsics,
        "cam_img_w": camera.width,
        "cam_img_h": camera.height,
        "distortion_model": np.array(camera.distortion_model),
        "distortion_coeffs": np.array(camera.distortion_coeffs),
    }
    auto = frame_source_from_cam_data(cam_data, distortion_mode="auto")
    raw = frame_source_from_cam_data(cam_data, distortion_mode="raw")
    assert auto.pixel_space == PINHOLE_SPACE
    assert raw.pixel_space == RAW_SPACE
    assert not np.array_equal(auto.read_rgb(0), raw.read_rgb(0))
    assert np.array_equal(auto.read_rgb(0), undistort_rgb(image, camera))


def test_auto_zero_distortion_is_a_pinhole_noop():
    camera = make_camera(coeffs=(0.0, 0.0, 0.0, 0.0, 0.0))
    assert resolve_distortion_mode("auto", camera) == (False, PINHOLE_SPACE)


def test_auto_rejects_unknown_nonzero_distortion_model():
    camera = make_camera(model="fisheye", coeffs=(0.1, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="unsupported distortion model"):
        resolve_distortion_mode("auto", camera)


def test_manifest_rejects_mixed_mask_and_landmark_geometry(tmp_path):
    camera = make_camera()
    masks = tmp_path / "masks"
    canonical = geometry_record(camera, "auto")
    write_geometry_manifest(masks, "ma_masks", [canonical])
    assert validate_geometry_manifest(masks, [canonical], "ma_2d")

    raw = geometry_record(camera, "raw")
    with pytest.raises(ValueError, match="incompatible cached pixel geometry"):
        validate_geometry_manifest(masks, [raw], "ma_2d")


def test_optimizer_rejects_raw_distorted_landmarks(tmp_path):
    prediction_dir = tmp_path / "ma_2d"
    write_geometry_manifest(prediction_dir, "ma_2d", [geometry_record(make_camera(), "raw")])
    with pytest.raises(ValueError, match="pinhole projector"):
        require_pinhole_optimizer_geometry(prediction_dir)

    write_geometry_manifest(prediction_dir, "ma_2d", [geometry_record(make_camera(), "auto")])
    assert require_pinhole_optimizer_geometry(prediction_dir)


def test_builder_defaults_to_auto_and_honors_legacy_alias():
    builder = StepBuilder({}, {}, "test")
    assert builder._distortion_mode_flag() == ["--distortion-mode", "auto"]
    legacy = StepBuilder({"undistort": False}, {}, "test")
    assert legacy._distortion_mode_flag() == ["--distortion-mode", "raw"]


def test_geometry_manifest_is_stable_json(tmp_path):
    path = write_geometry_manifest(tmp_path, "ma_2d", [geometry_record(make_camera(), "auto")])
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == 1
    assert payload["cameras"]["cam00"]["pixel_space"] == PINHOLE_SPACE
