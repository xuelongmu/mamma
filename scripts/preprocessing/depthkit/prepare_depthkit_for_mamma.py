#!/usr/bin/env python3
"""Prepare synchronized Depthkit/Scatter RGB recordings for MAMMA.

The script converts ``dkproject.json`` calibration to MAMMA's flat OpenCV
JSON format and creates the ``<sequence>/videos/<camera>.mp4`` layout.  Source
videos are linked when already conformant; ``--video-mode reencode`` is
available for sources that need constant-frame-rate H.264 preprocessing.

Depthkit/Scatter convention validated for the Xuelong rig:

* ``worldExtrinsics.world`` is a depth-camera-to-world pose.
* The stored world pose is left-handed and must be conjugated into a
  right-handed coordinate system.
* Color calibration extrinsics map depth-camera coordinates to color-camera
  coordinates (overridable for other exporters).
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

import cv2
import numpy as np

SCATTER_HANDEDNESS = np.diag([1.0, 1.0, -1.0, 1.0])
SENSOR_RE = re.compile(r"Sensor(?P<number>\d+)-", re.IGNORECASE)


class ConversionError(RuntimeError):
    """A user-actionable project or conversion error."""


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


@dataclass(frozen=True)
class CameraStream:
    name: str
    sensor_number: int
    device_id: str
    source: Path
    width: int
    height: int
    fps: float
    frame_count: int
    calibration: dict[str, Any]
    world_pose: dict[str, Any]
    stream: dict[str, Any]


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ConversionError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConversionError(f"Invalid JSON in {path}: {exc}") from exc


def discover_project_root(start: Path) -> Path:
    start = start.resolve()
    if start.is_file() and start.name.lower() == "dkproject.json":
        return start.parent
    if (start / "dkproject.json").is_file():
        return start
    matches = list(start.rglob("dkproject.json")) if start.is_dir() else []
    if len(matches) == 1:
        return matches[0].parent
    if not matches:
        raise ConversionError(f"Could not find dkproject.json beneath {start}")
    raise ConversionError(
        f"Found {len(matches)} Depthkit projects beneath {start}; pass one explicitly"
    )


def pose_matrix(pose: dict[str, Any]) -> np.ndarray:
    rotation = np.asarray(pose["rotation"], dtype=np.float64)
    translation = np.asarray(pose["translation"], dtype=np.float64)
    if rotation.shape != (3,) or translation.shape != (3,):
        raise ConversionError(
            "Expected three-element Rodrigues rotation and translation"
        )
    if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ConversionError("Camera pose contains a non-finite value")
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = cv2.Rodrigues(rotation)[0]
    matrix[:3, 3] = translation
    return matrix


def color_camera_to_world(
    world_pose: dict[str, Any],
    color_extrinsics: dict[str, Any],
    direction: str = "depth-to-color",
) -> np.ndarray:
    """Return a proper, right-handed color-camera-to-world transform."""
    stored_world = pose_matrix(world_pose)
    world_from_depth = SCATTER_HANDEDNESS @ stored_world @ SCATTER_HANDEDNESS
    extrinsics = pose_matrix(color_extrinsics)
    if direction == "color-to-depth":
        depth_from_color = extrinsics
    elif direction == "depth-to-color":
        depth_from_color = np.linalg.inv(extrinsics)
    else:  # pragma: no cover - argparse prevents this
        raise AssertionError(direction)
    world_from_color = world_from_depth @ depth_from_color
    rotation = world_from_color[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
        raise ConversionError("Converted camera rotation is not orthonormal")
    determinant = float(np.linalg.det(rotation))
    if not np.isclose(determinant, 1.0, atol=1e-6):
        raise ConversionError(
            f"Converted camera rotation is improper: det={determinant}"
        )
    return world_from_color


def sensor_number(asset_path: str) -> int:
    match = SENSOR_RE.search(asset_path)
    if match is None:
        raise ConversionError(f"Cannot read SensorNN from asset path: {asset_path}")
    return int(match["number"])


def resolve_asset(project_root: Path, asset_path: str) -> Path:
    return project_root / Path(asset_path.replace("\\", "/"))


def stream_of_type(
    streams: Iterable[dict[str, Any]], kind: str
) -> dict[str, Any] | None:
    return next((stream for stream in streams if stream.get("type") == kind), None)


def calibration_for_stream(
    device: dict[str, Any], stream: dict[str, Any], kind: str
) -> dict[str, Any]:
    source = next(
        (item for item in device.get("sources", []) if item.get("type") == kind), None
    )
    if source is None:
        raise ConversionError(f"Device lacks a {kind!r} source")
    profile_name = stream.get("calibration")
    calibration = source.get("calibrations", {}).get(profile_name)
    if calibration is None:
        raise ConversionError(f"Missing {kind} calibration profile {profile_name!r}")
    return calibration


def inspect_video(path: Path) -> tuple[int, int, float, int]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise ConversionError(f"Cannot open video: {path}")
    width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    capture.release()
    if min(width, height, count) <= 0 or not math.isfinite(fps) or fps <= 0:
        raise ConversionError(f"Invalid video metadata: {path}")
    return width, height, fps, count


def rate_as_float(value: str) -> float:
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ConversionError(f"Invalid ffprobe frame rate: {value!r}") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise ConversionError(f"Invalid ffprobe frame rate: {value!r}")
    return rate


def video_is_conformant_for_symlink(path: Path, target_fps: int) -> bool:
    """Return whether ffprobe metadata is safe for automatic direct reuse."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,r_frame_rate,avg_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        if len(streams) != 1:
            return False
        stream = streams[0]
        nominal_fps = rate_as_float(stream["r_frame_rate"])
        average_fps = rate_as_float(stream["avg_frame_rate"])
    except (
        ConversionError,
        FileNotFoundError,
        KeyError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ):
        return False
    return (
        stream.get("codec_name") == "h264"
        and stream.get("pix_fmt") == "yuv420p"
        and math.isclose(nominal_fps, target_fps, abs_tol=1e-3)
        and math.isclose(average_fps, target_fps, abs_tol=1e-3)
    )


def recording_is_available(project_root: Path, recording: dict[str, Any]) -> bool:
    color_streams = [
        stream_of_type(streams, "color")
        for streams in recording.get("streams", {}).values()
    ]
    return bool(color_streams) and all(
        stream is not None
        and resolve_asset(project_root, stream["assetPath"]).is_file()
        for stream in color_streams
    )


def gather_recording(
    project_root: Path, project: dict[str, Any], recording_name: str
) -> list[CameraStream]:
    recording = project.get("recordings", {}).get(recording_name)
    if recording is None:
        raise ConversionError(
            f"Recording {recording_name!r} is absent from dkproject.json"
        )
    cameras: list[CameraStream] = []
    for device_id, streams in recording.get("streams", {}).items():
        color_stream = stream_of_type(streams, "color")
        if color_stream is None:
            raise ConversionError(
                f"Recording {recording_name!r} device {device_id!r} lacks a color stream"
            )
        source = resolve_asset(project_root, color_stream["assetPath"])
        if not source.is_file():
            raise ConversionError(f"Missing color video for {recording_name}: {source}")
        device = project.get("deviceConfigurations", {}).get(device_id)
        if device is None:
            raise ConversionError(f"Missing device calibration: {device_id}")
        calibration = calibration_for_stream(device, color_stream, "color")
        width, height, fps, count = inspect_video(source)
        expected = tuple(map(int, calibration["intrinsics"]["imageSize"]))
        if (width, height) != expected:
            raise ConversionError(
                f"{source} is {width}x{height}; calibration {color_stream['calibration']} "
                f"is {expected[0]}x{expected[1]}"
            )
        number = sensor_number(color_stream["assetPath"])
        cameras.append(
            CameraStream(
                name=f"cam_{number:02d}",
                sensor_number=number,
                device_id=device_id,
                source=source,
                width=width,
                height=height,
                fps=fps,
                frame_count=count,
                calibration=calibration,
                world_pose=device["worldExtrinsics"]["world"],
                stream=color_stream,
            )
        )
    cameras.sort(key=lambda camera: camera.sensor_number)
    if len(cameras) < 2:
        raise ConversionError(
            f"Recording {recording_name!r} has fewer than two cameras"
        )
    if len({camera.name for camera in cameras}) != len(cameras):
        raise ConversionError(
            f"Recording {recording_name!r} contains duplicate sensor numbers"
        )
    return cameras


def distortion_coefficients(intrinsics: dict[str, Any]) -> list[float]:
    radial = [float(value) for value in intrinsics.get("distortionRadial", [])]
    tangential = [float(value) for value in intrinsics.get("distortionTangential", [])]
    if not all(math.isfinite(value) for value in [*radial, *tangential]):
        raise ConversionError("Camera distortion contains a non-finite value")
    if any(abs(value) > 1e-10 for value in radial[3:]) or any(
        abs(value) > 1e-10 for value in tangential[2:]
    ):
        raise ConversionError(
            "MAMMA's OpenCV JSON accepts only k1,k2,p1,p2,k3, but this "
            "Depthkit profile has non-zero unsupported distortion coefficients"
        )
    radial += [0.0] * max(0, 3 - len(radial))
    tangential += [0.0] * max(0, 2 - len(tangential))
    return [radial[0], radial[1], tangential[0], tangential[1], radial[2]]


def rotate_opencv_camera(calibration: dict[str, Any], rotation: str) -> dict[str, Any]:
    """Rotate image coordinates and the matching OpenCV camera model."""
    if rotation == "none":
        return calibration
    result = json.loads(json.dumps(calibration))
    k = np.asarray(result["intrinsic_matrix"], dtype=np.float64)
    extrinsics = np.asarray(result["extrinsics_matrix"], dtype=np.float64)
    k1, k2, p1, p2, k3 = map(float, result["distortions"])
    width, height = map(int, result["image_size"])
    fx, fy, cx, cy = k[0, 0], k[1, 1], k[0, 2], k[1, 2]
    if rotation == "ccw":
        camera_rotation = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        new_k = np.array([[fy, 0.0, cy], [0.0, fx, width - 1.0 - cx], [0.0, 0.0, 1.0]])
        new_distortion = [k1, k2, -p2, p1, k3]
        new_size = [height, width]
    elif rotation == "cw":
        camera_rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        new_k = np.array([[fy, 0.0, height - 1.0 - cy], [0.0, fx, cx], [0.0, 0.0, 1.0]])
        new_distortion = [k1, k2, p2, -p1, k3]
        new_size = [height, width]
    elif rotation == "180":
        camera_rotation = np.diag([-1.0, -1.0, 1.0])
        new_k = np.array(
            [[fx, 0.0, width - 1.0 - cx], [0.0, fy, height - 1.0 - cy], [0.0, 0.0, 1.0]]
        )
        new_distortion = [k1, k2, -p1, -p2, k3]
        new_size = [width, height]
    else:  # pragma: no cover - argparse prevents this
        raise AssertionError(rotation)
    result["intrinsic_matrix"] = new_k.tolist()
    result["distortions"] = new_distortion
    result["extrinsics_matrix"] = (camera_rotation @ extrinsics).tolist()
    result["image_size"] = new_size
    return result


def mamma_camera(
    camera: CameraStream,
    rotation: str = "none",
    color_extrinsics_direction: str = "depth-to-color",
) -> dict[str, Any]:
    intrinsics = camera.calibration["intrinsics"]
    fx, fy = map(float, intrinsics["focalLength"])
    cx, cy = map(float, intrinsics["principalPoint"])
    if not all(math.isfinite(value) for value in (fx, fy, cx, cy)):
        raise ConversionError(f"{camera.name} intrinsics contain a non-finite value")
    if fx <= 0 or fy <= 0:
        raise ConversionError(f"{camera.name} has a non-positive focal length")
    world_from_color = color_camera_to_world(
        camera.world_pose,
        camera.calibration["extrinsics"],
        color_extrinsics_direction,
    )
    color_from_world = np.linalg.inv(world_from_color)
    calibration = {
        "intrinsic_matrix": [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
        "distortions": distortion_coefficients(intrinsics),
        "extrinsics_matrix": color_from_world[:3, :].tolist(),
        "image_size": [camera.width, camera.height],
    }
    return rotate_opencv_camera(calibration, rotation)


def camera_look_at_score(
    cameras: list[CameraStream], color_extrinsics_direction: str
) -> float:
    poses = [
        color_camera_to_world(
            camera.world_pose,
            camera.calibration["extrinsics"],
            color_extrinsics_direction,
        )
        for camera in cameras
    ]
    centers = np.asarray([pose[:3, 3] for pose in poses])
    centroid = centers.mean(axis=0)
    scores: list[float] = []
    for pose, center in zip(poses, centers):
        direction = centroid - center
        norm = float(np.linalg.norm(direction))
        if norm > 1e-9:
            scores.append(float(np.dot(pose[:3, 2], direction / norm)))
    if not scores:
        raise ConversionError("Camera rig has no distinct camera centers")
    score = float(np.mean(scores))
    if not math.isfinite(score):
        raise ConversionError("Camera look-at score is non-finite")
    return score


def look_at_score_warning(score: float) -> str | None:
    if score < 0.5:
        return (
            "Camera look-at score is low for a surrounding inward-looking rig; "
            "parallel/front-facing arrays can legitimately have a low score, so "
            "verify the intended rig geometry"
        )
    return None


def write_json(path: Path, value: Any, overwrite: bool) -> None:
    serialized = json.dumps(value, indent=2) + "\n"
    if path.exists() and not overwrite:
        if path.read_text(encoding="utf-8") == serialized:
            return
        raise ConversionError(f"Refusing to overwrite {path}; pass --overwrite")
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)


def replaceable_destination(
    destination: Path,
    source: Path,
    overwrite: bool,
    *,
    reuse_matching_symlink: bool,
) -> bool:
    if not os.path.lexists(destination):
        return True
    if (
        reuse_matching_symlink
        and destination.is_symlink()
        and destination.resolve() == source.resolve()
    ):
        return False
    if not overwrite:
        raise ConversionError(f"Refusing to overwrite {destination}; pass --overwrite")
    if destination.is_dir() and not destination.is_symlink():
        raise ConversionError(
            f"Expected a video file but found a directory: {destination}"
        )
    return True


def effective_video_mode(
    camera: CameraStream,
    mode: str,
    target_fps: float,
    rotation: str,
) -> str:
    actual_mode = mode
    if mode == "auto":
        actual_mode = (
            "symlink"
            if rotation == "none"
            and video_is_conformant_for_symlink(camera.source, int(target_fps))
            else "reencode"
        )
    if rotation != "none" and actual_mode in ("symlink", "copy"):
        raise ConversionError(
            f"--video-mode {actual_mode} cannot apply --rotate {rotation}; "
            "use auto or reencode"
        )
    if actual_mode in ("symlink", "copy") and not math.isclose(
        camera.fps,
        target_fps,
        abs_tol=1e-3,
    ):
        raise ConversionError(
            f"--video-mode {actual_mode} cannot change {camera.name} from "
            f"{camera.fps:g} to {target_fps:g} fps; use auto or reencode"
        )
    return actual_mode


def prepare_video(
    camera: CameraStream,
    destination: Path,
    mode: str,
    target_fps: float,
    overwrite: bool,
    rotation: str,
) -> str:
    actual_mode = effective_video_mode(camera, mode, target_fps, rotation)
    if not replaceable_destination(
        destination,
        camera.source,
        overwrite,
        reuse_matching_symlink=actual_mode == "symlink",
    ):
        return actual_mode
    temporary = destination.with_name(
        f".{destination.stem}.partial{destination.suffix}"
    )
    if os.path.lexists(temporary):
        temporary.unlink()
    try:
        if actual_mode == "symlink":
            temporary.symlink_to(camera.source)
        elif actual_mode == "copy":
            shutil.copy2(camera.source, temporary)
        elif actual_mode == "reencode":
            rotation_filter = {
                "none": [],
                "ccw": ["transpose=2"],
                "cw": ["transpose=1"],
                "180": ["hflip", "vflip"],
            }[rotation]
            filters = [*rotation_filter, f"fps={target_fps:g}"]
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(camera.source),
                "-an",
                "-vf",
                ",".join(filters),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(temporary),
            ]
            subprocess.run(command, check=True)
        else:  # pragma: no cover - argparse prevents this
            raise AssertionError(actual_mode)
        temporary.replace(destination)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()
    return actual_mode


def preflight_non_overwrite(
    output: Path,
    takes: dict[str, list[CameraStream]],
    mode: str,
    target_fps: float,
    rotation: str,
) -> None:
    preflight_destination_containment(output, takes)
    for name in ("calibration.json", "capture.json", "conversion_manifest.json"):
        descriptor = output / name
        if os.path.lexists(descriptor):
            raise ConversionError(
                f"Refusing to overwrite {descriptor}; pass --overwrite"
            )
    for recording_name, cameras in takes.items():
        for camera in cameras:
            destination = output / recording_name / "videos" / f"{camera.name}.mp4"
            if not os.path.lexists(destination):
                continue
            actual_mode = effective_video_mode(
                camera,
                mode,
                target_fps,
                rotation,
            )
            if (
                actual_mode == "symlink"
                and destination.is_symlink()
                and destination.resolve() == camera.source.resolve()
            ):
                continue
            raise ConversionError(
                f"Refusing to overwrite {destination}; pass --overwrite"
            )


def preflight_overwrite(
    output: Path,
    takes: dict[str, list[CameraStream]],
    mode: str,
    target_fps: float,
    rotation: str,
) -> None:
    preflight_destination_containment(output, takes)
    for recording_name, cameras in takes.items():
        for camera in cameras:
            effective_video_mode(camera, mode, target_fps, rotation)
            destination = output / recording_name / "videos" / f"{camera.name}.mp4"
            if destination.is_dir() or (
                destination.is_symlink() and not destination.is_file()
            ):
                raise ConversionError(
                    f"Expected a video file but found a directory: {destination}"
                )
            temporary = destination.with_name(
                f".{destination.stem}.partial{destination.suffix}"
            )
            if temporary.is_dir() or (
                temporary.is_symlink() and not temporary.is_file()
            ):
                raise ConversionError(
                    f"Expected a temporary video file but found a directory: {temporary}"
                )


def preflight_destination_containment(
    output: Path,
    takes: dict[str, list[CameraStream]],
) -> None:
    output_root = output.resolve()
    for recording_name, cameras in takes.items():
        for camera in cameras:
            destination = output / recording_name / "videos" / f"{camera.name}.mp4"
            try:
                destination.parent.resolve().relative_to(output_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ConversionError(
                    f"Video destination escapes the output directory: {destination}"
                ) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def source_fingerprint(camera: CameraStream) -> dict[str, Any]:
    return file_fingerprint(camera.source)


def validate_prepared_video_identity(
    prior: dict[str, Any], destination: Path, prepared_frames: int
) -> None:
    try:
        prior_path = Path(prior["prepared"]).resolve()
        prior_frames = int(prior["prepared_frames"])
        prior_fingerprint = prior["prepared_fingerprint"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversionError(
            f"--calibration-only lacks prepared-video identity for {destination}"
        ) from exc
    if (
        prior_path != destination.resolve()
        or prior_frames != prepared_frames
        or prior_fingerprint != file_fingerprint(destination)
    ):
        raise ConversionError(
            f"--calibration-only prepared video changed: {destination}"
        )


def invalidate_capture_descriptors(output: Path) -> None:
    for name in ("calibration.json", "capture.json", "conversion_manifest.json"):
        (output / name).unlink(missing_ok=True)


def publish_capture_descriptors(
    output: Path,
    calibration: dict[str, Any],
    capture: dict[str, Any],
    manifest: dict[str, Any],
    *,
    overwrite: bool,
    invalidate_existing: bool,
) -> None:
    if invalidate_existing:
        invalidate_capture_descriptors(output)
    write_json(output / "calibration.json", calibration, overwrite)
    write_json(output / "capture.json", capture, overwrite)
    write_json(output / "conversion_manifest.json", manifest, overwrite)


def validate_recording_names(recording_names: list[str]) -> None:
    if len(set(recording_names)) != len(recording_names):
        raise ConversionError("Recording names must be unique")
    for name in recording_names:
        if (
            not isinstance(name, str)
            or not name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
            or Path(name).is_absolute()
            or PureWindowsPath(name).drive
        ):
            raise ConversionError(
                f"Recording name must be a safe single path component: {name!r}"
            )


def validate_synchronized_streams(
    takes: dict[str, list[CameraStream]],
) -> None:
    for name, cameras in takes.items():
        reference_offset = stream_sync_offset(cameras[0].stream)
        for camera in cameras:
            offset = stream_sync_offset(camera.stream)
            if offset != reference_offset:
                raise ConversionError(
                    f"Recording {name!r} has mismatched synchronization offsets: "
                    f"{camera.name} reports {offset}, expected {reference_offset}"
                )
            dropped_raw = camera.stream.get("numDroppedFrames", 0)
            if isinstance(dropped_raw, bool):
                raise ConversionError(
                    f"Invalid dropped-frame count for {name!r}/{camera.name}: "
                    f"{dropped_raw!r}"
                )
            try:
                dropped = float(dropped_raw)
            except (TypeError, ValueError) as exc:
                raise ConversionError(
                    f"Invalid dropped-frame count for {name!r}/{camera.name}: "
                    f"{dropped_raw!r}"
                ) from exc
            if not math.isfinite(dropped) or dropped < 0 or not dropped.is_integer():
                raise ConversionError(
                    f"Invalid dropped-frame count for {name!r}/{camera.name}: "
                    f"{dropped_raw!r}"
                )
            if dropped > 0:
                raise ConversionError(
                    f"Recording {name!r}/{camera.name} reports "
                    f"{int(dropped)} dropped capture frame(s); MAMMA aligns views "
                    "by frame index, so repair the synchronized timeline first"
                )


def stream_sync_offset(stream: dict[str, Any]) -> Fraction:
    offset = stream.get("syncOffset")
    if offset is None:
        return Fraction(0, 1)
    if not isinstance(offset, dict):
        raise ConversionError(f"Invalid stream synchronization offset: {offset!r}")
    negative = offset.get("negative", False)
    ticks_raw = offset.get("ticks", 0)
    timebase_raw = offset.get("timebase", 1)
    if (
        not isinstance(negative, bool)
        or isinstance(ticks_raw, bool)
        or isinstance(timebase_raw, bool)
    ):
        raise ConversionError(f"Invalid stream synchronization offset: {offset!r}")
    try:
        ticks = int(ticks_raw)
        timebase = int(timebase_raw)
    except (TypeError, ValueError) as exc:
        raise ConversionError(
            f"Invalid stream synchronization offset: {offset!r}"
        ) from exc
    if ticks != ticks_raw or timebase != timebase_raw or ticks < 0 or timebase <= 0:
        raise ConversionError(f"Invalid stream synchronization offset: {offset!r}")
    value = Fraction(ticks, timebase)
    return -value if negative else value


def validate_common_source_fps(
    takes: dict[str, list[CameraStream]], tolerance: float = 1e-3
) -> float:
    first_recording = next(iter(takes.values()))
    reference_fps = first_recording[0].fps
    for name, cameras in takes.items():
        for camera in cameras:
            if not math.isclose(
                camera.fps,
                reference_fps,
                rel_tol=0.0,
                abs_tol=tolerance,
            ):
                raise ConversionError(
                    f"Source frame rates are not synchronized: {name!r}/{camera.name} "
                    f"reports {camera.fps:g} fps, expected {reference_fps:g} fps"
                )
    return reference_fps


def validate_calibration_only_manifest(
    output: Path,
    rotation: str,
    project_root: Path,
    takes: dict[str, list[CameraStream]],
) -> dict[str, Any]:
    manifest_path = output / "conversion_manifest.json"
    try:
        manifest = load_json(manifest_path)
    except ConversionError as exc:
        raise ConversionError(
            "--calibration-only requires a valid existing conversion manifest"
        ) from exc
    if manifest.get("rotation") != rotation:
        raise ConversionError(
            "--calibration-only cannot change image rotation; "
            "re-run video preparation with --overwrite"
        )
    try:
        prior_project = Path(manifest["source_project"]).resolve()
        prior_calibration_sha256 = manifest["source_calibration_sha256"]
        prior_takes = manifest["recordings"]
    except (KeyError, TypeError) as exc:
        raise ConversionError(
            "--calibration-only requires source identity metadata from a "
            "current conversion manifest"
        ) from exc
    if not isinstance(prior_takes, dict):
        raise ConversionError(
            "--calibration-only requires valid recording identity metadata"
        )
    calibration_path = project_root / "dkproject.json"
    if (
        prior_project != project_root.resolve()
        or prior_calibration_sha256 != sha256_file(calibration_path)
    ):
        raise ConversionError(
            "--calibration-only source project or calibration does not match "
            "the existing conversion manifest"
        )
    if set(prior_takes) != set(takes):
        raise ConversionError(
            "--calibration-only recording set does not match the existing manifest"
        )
    for name, cameras in takes.items():
        records = prior_takes.get(name)
        if not isinstance(records, list):
            raise ConversionError(
                f"--calibration-only has invalid prior records for {name!r}"
            )
        prior_by_camera = {
            record.get("camera"): record
            for record in records
            if isinstance(record, dict) and isinstance(record.get("camera"), str)
        }
        expected_camera_names = {camera.name for camera in cameras}
        if (
            len(prior_by_camera) != len(records)
            or set(prior_by_camera) != expected_camera_names
        ):
            raise ConversionError(
                f"--calibration-only camera set changed for recording {name!r}"
            )
        for camera in cameras:
            prior = prior_by_camera[camera.name]
            try:
                prior_source = Path(prior["source"]).resolve()
            except (KeyError, TypeError) as exc:
                raise ConversionError(
                    f"--calibration-only lacks source identity for "
                    f"{name!r}/{camera.name}"
                ) from exc
            if (
                prior.get("device_id") != camera.device_id
                or prior_source != camera.source.resolve()
                or prior.get("source_fingerprint") != source_fingerprint(camera)
            ):
                raise ConversionError(
                    f"--calibration-only source changed for {name!r}/{camera.name}"
                )
    return manifest


def calibrations_match(
    reference: dict[str, Any], candidate: dict[str, Any], tolerance: float = 1e-8
) -> bool:
    return (
        reference["image_size"] == candidate["image_size"]
        and np.allclose(
            reference["intrinsic_matrix"],
            candidate["intrinsic_matrix"],
            atol=tolerance,
            rtol=0.0,
        )
        and np.allclose(
            reference["distortions"],
            candidate["distortions"],
            atol=tolerance,
            rtol=0.0,
        )
        and np.allclose(
            reference["extrinsics_matrix"],
            candidate["extrinsics_matrix"],
            atol=tolerance,
            rtol=0.0,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project", type=Path, help="Depthkit project root or dkproject.json"
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="Prepared MAMMA dataset directory; omit with --validate-only",
    )
    parser.add_argument(
        "--recordings",
        nargs="+",
        default=[],
        help="Recording names; defaults to every recording whose RGB assets exist",
    )
    parser.add_argument(
        "--fps",
        type=positive_integer,
        default=None,
        help=(
            "Positive integral output FPS. When omitted, the nearest integral "
            "rate to the first source is used."
        ),
    )
    parser.add_argument(
        "--video-mode", choices=("auto", "symlink", "copy", "reencode"), default="auto"
    )
    parser.add_argument(
        "--rotate",
        choices=("none", "ccw", "cw", "180"),
        default="none",
        help="Rotate every RGB stream and transform calibration to match",
    )
    parser.add_argument(
        "--color-extrinsics-direction",
        choices=("color-to-depth", "depth-to-color"),
        default="depth-to-color",
        help="Direction of color-profile extrinsics in dkproject.json",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--calibration-only",
        action="store_true",
        help="Rewrite metadata while reusing already-prepared destination videos",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = discover_project_root(args.project)
    project = load_json(project_root / "dkproject.json")
    recording_names = list(args.recordings)
    if not recording_names:
        recording_names = [
            name
            for name, recording in project.get("recordings", {}).items()
            if recording_is_available(project_root, recording)
        ]
    if not recording_names:
        raise ConversionError("No requested/available recordings were found")
    validate_recording_names(recording_names)

    takes = {
        name: gather_recording(project_root, project, name) for name in recording_names
    }
    validate_synchronized_streams(takes)
    source_fps = validate_common_source_fps(takes)
    first = next(iter(takes.values()))
    expected_rig = [(camera.name, camera.device_id) for camera in first]
    for name, cameras in takes.items():
        rig = [(camera.name, camera.device_id) for camera in cameras]
        if rig != expected_rig:
            raise ConversionError(
                f"Recording {name!r} does not use the same camera rig"
            )
    fps = int(args.fps if args.fps is not None else round(source_fps))
    if fps <= 0:
        raise ConversionError("Cannot derive a positive integral output FPS")
    score = camera_look_at_score(first, args.color_extrinsics_direction)
    calibration = {
        camera.name: mamma_camera(camera, args.rotate, args.color_extrinsics_direction)
        for camera in first
    }
    for name, cameras in takes.items():
        for camera in cameras:
            candidate = mamma_camera(
                camera, args.rotate, args.color_extrinsics_direction
            )
            if not calibrations_match(calibration[camera.name], candidate):
                raise ConversionError(
                    f"{name!r} uses different calibration for {camera.name}; "
                    "prepare recordings with a shared rig separately"
                )
    print(
        f"Validated {len(takes)} recording(s), {len(first)} cameras, look-at score={score:.4f}"
    )
    warning = look_at_score_warning(score)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    for name, cameras in takes.items():
        counts = [camera.frame_count for camera in cameras]
        print(
            f"  {name}: {min(counts)}..{max(counts)} frames at ~{cameras[0].fps:g} fps"
        )
    if args.validate_only:
        return

    if args.output is None:
        raise ConversionError("Output is required unless --validate-only is set")
    output = args.output.resolve()
    if (
        output == project_root
        or project_root.is_relative_to(output)
        or output.is_relative_to(project_root)
    ):
        raise ConversionError(
            "Output must be separate from the source project and its ancestors"
        )
    output.mkdir(parents=True, exist_ok=True)

    prior_manifest: dict[str, Any] | None = None
    if not args.calibration_only and not args.overwrite:
        preflight_non_overwrite(
            output,
            takes,
            args.video_mode,
            fps,
            args.rotate,
        )
    if args.calibration_only:
        preflight_destination_containment(output, takes)
        prior_manifest = validate_calibration_only_manifest(
            output,
            args.rotate,
            project_root,
            takes,
        )
    elif args.overwrite:
        preflight_overwrite(
            output,
            takes,
            args.video_mode,
            fps,
            args.rotate,
        )
        invalidate_capture_descriptors(output)

    manifest_takes: dict[str, Any] = {}
    for name, cameras in takes.items():
        videos_dir = output / name / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for camera in cameras:
            destination = videos_dir / f"{camera.name}.mp4"
            prepared_size = calibration[camera.name]["image_size"]
            if args.calibration_only:
                if not destination.is_file():
                    raise ConversionError(
                        f"--calibration-only requires existing video: {destination}"
                    )
                width, height, prepared_fps, prepared_frames = inspect_video(
                    destination
                )
                if [width, height] != prepared_size:
                    raise ConversionError(
                        f"Existing {destination} is {width}x{height}; "
                        f"calibration expects {prepared_size[0]}x{prepared_size[1]}"
                    )
                if abs(prepared_fps - fps) >= 1e-3:
                    raise ConversionError(
                        f"Existing {destination} is {prepared_fps:g} fps; expected {fps:g}"
                    )
                assert prior_manifest is not None
                prior = next(
                    record
                    for record in prior_manifest["recordings"][name]
                    if record["camera"] == camera.name
                )
                validate_prepared_video_identity(
                    prior,
                    destination,
                    prepared_frames,
                )
                action = "existing"
            else:
                action = prepare_video(
                    camera,
                    destination,
                    args.video_mode,
                    fps,
                    args.overwrite,
                    args.rotate,
                )
                width, height, prepared_fps, prepared_frames = inspect_video(
                    destination
                )
                if [width, height] != prepared_size:
                    raise ConversionError(
                        f"Prepared {destination} is {width}x{height}; "
                        f"calibration expects {prepared_size[0]}x{prepared_size[1]}"
                    )
                if abs(prepared_fps - fps) >= 1e-3:
                    raise ConversionError(
                        f"Prepared {destination} is {prepared_fps:g} fps; expected {fps:g}"
                    )
            records.append(
                {
                    "camera": camera.name,
                    "device_id": camera.device_id,
                    "source": str(camera.source),
                    "prepared": str(destination),
                    "action": action,
                    "source_resolution": [camera.width, camera.height],
                    "prepared_resolution": prepared_size,
                    "rotation": args.rotate,
                    "fps": camera.fps,
                    "source_frames": camera.frame_count,
                    "prepared_frames": prepared_frames,
                    "prepared_fingerprint": file_fingerprint(destination),
                    "source_fingerprint": source_fingerprint(camera),
                    "sync_offset": camera.stream.get("syncOffset"),
                    "dropped_frames": camera.stream.get("numDroppedFrames", 0),
                }
            )
        manifest_takes[name] = records

    capture = {
        "capture_root": ".",
        "calib": "calibration.json",
        "cam_fps": fps,
        "videos_subdir": "videos",
        "cams": [camera.name for camera in first],
        "sequences": {
            f"{index:03d}": {"name": name} for index, name in enumerate(recording_names)
        },
    }
    manifest = {
        "source_project": str(project_root),
        "source_calibration": str(project_root / "dkproject.json"),
        "source_calibration_sha256": sha256_file(project_root / "dkproject.json"),
        "world_extrinsics_direction": "camera-to-world",
        "world_pose_handedness_conversion": "H @ stored_world @ H; H=diag(1,1,-1,1)",
        "mamma_camera_basis": "opencv",
        "color_extrinsics_direction": args.color_extrinsics_direction,
        "look_at_score": score,
        "video_mode": args.video_mode,
        "rotation": args.rotate,
        "fps": fps,
        "recordings": manifest_takes,
    }
    publish_capture_descriptors(
        output,
        calibration,
        capture,
        manifest,
        overwrite=args.overwrite,
        invalidate_existing=args.calibration_only and args.overwrite,
    )
    print(f"Wrote MAMMA capture descriptor: {output / 'capture.json'}")


if __name__ == "__main__":
    try:
        main()
    except ConversionError as exc:
        raise SystemExit(f"error: {exc}") from exc
