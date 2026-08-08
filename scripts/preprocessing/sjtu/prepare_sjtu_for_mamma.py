#!/usr/bin/env python3
"""Conform an SJTU multi-view sports clip for MAMMA.

SJTU's ``paras.txt`` stores camera-to-world rotations as
``Xc = R @ (Xw - C)`` and camera centers in rig units. MAMMA expects a
metric world-to-camera matrix, so this adapter writes ``[R | -R @ C_m]``.
The metric conversion is estimated from the documented spacing between
adjacent cameras using the median separation in the calibration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return parsed


def nonnegative_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return parsed


def single_path_component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("must be a single directory name")
    return value


def validate_unique_camera_ids(camera_ids: list[int]) -> None:
    if len(set(camera_ids)) != len(camera_ids):
        raise ValueError("--camera-ids must not contain duplicates")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("session", type=single_path_component)
    parser.add_argument("--camera-ids", nargs="+", type=int, default=list(range(12)))
    parser.add_argument(
        "--start-seconds", type=nonnegative_finite_float, default=0.0
    )
    parser.add_argument(
        "--duration",
        type=positive_finite_float,
        default=None,
        help="Clip duration in seconds; omit to encode through the source end.",
    )
    parser.add_argument(
        "--fps",
        type=positive_integer,
        default=25,
        help="Positive integral frame rate (the current MAMMA capture path stores an integer).",
    )
    parser.add_argument(
        "--adjacent-spacing-metres",
        type=positive_finite_float,
        default=0.46,
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def mat_vec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[j] * vector[j] for j in range(3)) for row in matrix]


def validate_rotation_matrix(
    rotation: list[list[float]], camera_id: int, tolerance: float = 1e-4
) -> None:
    for column_a in range(3):
        for column_b in range(3):
            dot = sum(
                rotation[row][column_a] * rotation[row][column_b]
                for row in range(3)
            )
            expected = 1.0 if column_a == column_b else 0.0
            if abs(dot - expected) > tolerance:
                raise ValueError(
                    f"Non-orthonormal rotation for camera {camera_id}"
                )
    determinant = (
        rotation[0][0]
        * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1]
        * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2]
        * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if abs(determinant - 1.0) > tolerance:
        raise ValueError(
            f"Improper rotation for camera {camera_id}: determinant {determinant:g}"
        )


def parse_calibration(path: Path) -> dict[int, dict]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) % 5:
        raise ValueError(f"{path} does not contain five lines per camera")
    cameras: dict[int, dict] = {}
    for offset in range(0, len(lines), 5):
        camera_id = int(lines[offset].split()[1])
        if camera_id in cameras:
            raise ValueError(f"Duplicate calibration camera ID {camera_id}")
        width, height = map(int, lines[offset + 1].split()[1:])
        if width <= 0 or height <= 0:
            raise ValueError(
                f"Nonpositive image size for camera {camera_id}: "
                f"{width}x{height}"
            )
        fx, fy, cx, cy = map(float, lines[offset + 2].split()[1:])
        if fx <= 0 or fy <= 0:
            raise ValueError(
                f"Nonpositive focal length for camera {camera_id}: "
                f"fx={fx:g}, fy={fy:g}"
            )
        r_values = list(map(float, lines[offset + 3].split()[1:]))
        center = list(map(float, lines[offset + 4].split()[1:]))
        if len(r_values) != 9 or len(center) != 3:
            raise ValueError(f"Invalid calibration block for camera {camera_id}")
        numeric_values = [fx, fy, cx, cy, *r_values, *center]
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError(
                f"Non-finite calibration value for camera {camera_id}"
            )
        rotation = [r_values[row * 3 : (row + 1) * 3] for row in range(3)]
        validate_rotation_matrix(rotation, camera_id)
        cameras[camera_id] = {
            "width": width,
            "height": height,
            "intrinsic": [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
            "rotation": rotation,
            "center_units": center,
        }
    return cameras


def distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def metric_calibration(camera: dict, scale: float) -> dict:
    center_m = [value * scale for value in camera["center_units"]]
    translation = [-value for value in mat_vec(camera["rotation"], center_m)]
    extrinsics = [
        camera["rotation"][row] + [translation[row]] for row in range(3)
    ]
    return {
        "intrinsic_matrix": camera["intrinsic"],
        "distortions": [0.0] * 5,
        "extrinsics_matrix": extrinsics,
        "image_size": [camera["width"], camera["height"]],
    }


def preflight_video_jobs(
    dataset_root: Path,
    videos_dir: Path,
    camera_ids: list[int],
) -> list[tuple[int, str, Path, Path]]:
    jobs = []
    missing_sources = []
    for camera_id in camera_ids:
        source = dataset_root / "RGB" / f"{camera_id}.mp4"
        camera_name = f"cam_{camera_id:02d}"
        output = videos_dir / f"{camera_name}.mp4"
        if not source.is_file():
            missing_sources.append(source)
        jobs.append((camera_id, camera_name, source, output))

    if missing_sources:
        paths = "\n".join(f"- {path}" for path in missing_sources)
        raise FileNotFoundError(f"Missing source videos:\n{paths}")
    return jobs


def encode_video(source: Path, output: Path, video_filter: str) -> None:
    temporary = output.with_name(f".{output.stem}.partial{output.suffix}")
    temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-an", "-vf", video_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", str(temporary),
    ]
    try:
        subprocess.run(command, check=True)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def probe_video_frame_count(path: Path) -> int:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-count_frames", "-show_entries", "stream=nb_read_frames",
            "-of", "csv=p=0", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        frame_count = int(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"Could not determine video frame count for {path}"
        ) from exc
    if frame_count <= 0:
        raise RuntimeError(f"Video has no frames: {path}")
    return frame_count


def probe_video_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        width, height = map(int, result.stdout.strip().split("x"))
    except ValueError as exc:
        raise RuntimeError(
            f"Could not determine video dimensions for {path}"
        ) from exc
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Video has invalid dimensions {width}x{height}: {path}")
    return width, height


def validate_video_dimensions(
    camera_name: str,
    actual: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    if actual != expected:
        raise RuntimeError(
            f"{camera_name} video dimensions {actual[0]}x{actual[1]} do not "
            f"match calibration {expected[0]}x{expected[1]}"
        )


def validate_frame_count(
    camera_name: str,
    frame_count: int,
    expected_frame_count: int | None,
    reference_frame_count: int | None,
) -> None:
    if expected_frame_count is not None and frame_count != expected_frame_count:
        raise RuntimeError(
            f"{camera_name} has {frame_count} frames; expected "
            f"{expected_frame_count} for the requested duration"
        )
    if reference_frame_count is not None and frame_count != reference_frame_count:
        raise RuntimeError(
            f"{camera_name} has {frame_count} frames; the first camera has "
            f"{reference_frame_count}"
        )


def build_capture_descriptor(
    session: str, fps: int, camera_names: list[str]
) -> dict:
    return {
        # capture.json lives inside the session directory. Resolve these paths
        # relative to that file so the conformed tree remains portable.
        "capture_root": "..",
        "calib": "calibration.json",
        "cam_fps": fps,
        "videos_subdir": "videos",
        "cams": camera_names,
        "sequences": {"000": {"name": session}},
    }


def build_resume_signature(
    dataset_root: Path,
    start_seconds: float,
    duration_seconds: float | None,
    fps: int,
    adjacent_spacing_metres: float,
    calibration_sha256: str,
    source_fingerprints: list[dict],
) -> dict:
    return {
        "source": str(dataset_root.resolve()),
        "start_seconds": start_seconds,
        "duration_seconds": duration_seconds,
        "fps": fps,
        "adjacent_spacing_metres": adjacent_spacing_metres,
        "calibration_sha256": calibration_sha256,
        "source_fingerprints": source_fingerprints,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_sources(
    video_jobs: list[tuple[int, str, Path, Path]],
) -> list[dict]:
    fingerprints = []
    for camera_id, camera_name, source, _ in video_jobs:
        stat = source.stat()
        fingerprints.append({
            "camera": camera_name,
            "source_camera_id": camera_id,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return fingerprints


def validate_resume_manifest(
    manifest_path: Path,
    expected: dict,
    has_reusable_outputs: bool,
    overwrite: bool,
) -> set[str]:
    if overwrite or not has_reusable_outputs:
        return set()
    try:
        existing = json.loads(manifest_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Existing camera outputs cannot be verified without a valid "
            f"{manifest_path}; pass --overwrite or use a new session"
        ) from exc

    mismatches = [
        key for key, value in expected.items() if existing.get(key) != value
    ]
    if mismatches:
        raise RuntimeError(
            "Existing camera outputs were created with incompatible settings "
            f"({', '.join(mismatches)}); pass --overwrite or use a new session"
        )

    completed = existing.get("completed_cameras")
    if isinstance(completed, list):
        return {str(camera) for camera in completed}

    # Backward compatibility for manifests written before completion tracking.
    if existing.get("state") in (None, "complete"):
        return {
            str(record["camera"])
            for record in existing.get("records", [])
            if isinstance(record, dict) and record.get("camera")
        }
    return set()


def should_reuse_output(
    output: Path,
    camera_name: str,
    completed_cameras: set[str],
    overwrite: bool,
) -> bool:
    return output.exists() and camera_name in completed_cameras and not overwrite


def is_reuse_only(
    video_jobs: list[tuple[int, str, Path, Path]],
    completed_cameras: set[str],
    overwrite: bool,
) -> bool:
    return bool(video_jobs) and all(
        should_reuse_output(output, camera_name, completed_cameras, overwrite)
        for _, camera_name, _, output in video_jobs
    )


def write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def invalidate_capture_descriptors(session_dir: Path) -> None:
    for name in ("capture.json", "calibration.json"):
        (session_dir / name).unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    try:
        validate_unique_camera_ids(args.camera_ids)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    dataset_root = args.dataset_root.resolve()
    cameras = parse_calibration(dataset_root / "paras.txt")
    missing = sorted(set(args.camera_ids) - set(cameras))
    if missing:
        raise SystemExit(f"Missing camera calibrations: {missing}")

    ordered_ids = sorted(cameras)
    adjacent_distances = [
        distance(cameras[a]["center_units"], cameras[b]["center_units"])
        for a, b in zip(ordered_ids, ordered_ids[1:])
    ]
    if not adjacent_distances or min(adjacent_distances) <= 0:
        raise SystemExit("Cannot infer scale from adjacent camera centres")
    median_spacing_units = statistics.median(adjacent_distances)
    scale = args.adjacent_spacing_metres / median_spacing_units

    session_dir = args.output_root.resolve() / args.session
    videos_dir = session_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    try:
        video_jobs = preflight_video_jobs(
            dataset_root, videos_dir, args.camera_ids
        )
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    mamma_calibration: dict[str, dict] = {}
    records = []

    manifest_path = session_dir / "conformance.json"
    resume_signature = build_resume_signature(
        dataset_root,
        args.start_seconds,
        args.duration,
        args.fps,
        args.adjacent_spacing_metres,
        sha256_file(dataset_root / "paras.txt"),
        fingerprint_sources(video_jobs),
    )
    try:
        completed_cameras = validate_resume_manifest(
            manifest_path,
            resume_signature,
            has_reusable_outputs=any(job[3].exists() for job in video_jobs),
            overwrite=args.overwrite,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    reusable_cameras = completed_cameras
    completed_cameras = set()
    expected_frame_count = (
        None
        if args.duration is None
        else math.ceil(args.duration * args.fps - 1e-9)
    )
    capture_path = session_dir / "capture.json"
    calibration_path = session_dir / "calibration.json"
    if (
        is_reuse_only(video_jobs, reusable_cameras, args.overwrite)
        and capture_path.is_file()
        and calibration_path.is_file()
        and json.loads(manifest_path.read_text()).get("state") == "complete"
    ):
        reference_frame_count = None
        for camera_id, camera_name, _, output in video_jobs:
            frame_count = probe_video_frame_count(output)
            validate_frame_count(
                camera_name,
                frame_count,
                expected_frame_count,
                reference_frame_count,
            )
            if reference_frame_count is None:
                reference_frame_count = frame_count
            camera = cameras[camera_id]
            validate_video_dimensions(
                camera_name,
                probe_video_dimensions(output),
                (camera["width"], camera["height"]),
            )
        print(f"Capture already complete: {capture_path}", flush=True)
        return

    # Never leave an earlier completed descriptor published while final videos
    # are being replaced or an interrupted session is being resumed.
    invalidate_capture_descriptors(session_dir)
    manifest = {
        **resume_signature,
        "state": "encoding",
        "camera_order": args.camera_ids,
        "calibration_convention": "Xc = R @ Xw + (-R @ C_metres)",
        "adjacent_distances_rig_units": adjacent_distances,
        "median_adjacent_spacing_rig_units": median_spacing_units,
        "metres_per_rig_unit": scale,
        "completed_cameras": [],
        "frame_counts": {},
        "records": [],
    }
    write_json_atomic(manifest_path, manifest)

    reference_frame_count = None
    for camera_id, camera_name, source, output in video_jobs:
        video_filter = f"trim=start={args.start_seconds}"
        if args.duration is not None:
            video_filter += f":duration={args.duration}"
        video_filter += f",setpts=PTS-STARTPTS,fps={args.fps}"
        reuse_output = should_reuse_output(
            output, camera_name, reusable_cameras, args.overwrite
        )
        if reuse_output:
            print(f"Reusing completed {camera_name}: {output}", flush=True)
        else:
            print(f"Encoding source camera {camera_id} as {camera_name}", flush=True)
            encode_video(source, output, video_filter)

        camera = cameras[camera_id]
        frame_count = probe_video_frame_count(output)
        validate_frame_count(
            camera_name,
            frame_count,
            expected_frame_count,
            reference_frame_count,
        )
        if reference_frame_count is None:
            reference_frame_count = frame_count
        validate_video_dimensions(
            camera_name,
            probe_video_dimensions(output),
            (camera["width"], camera["height"]),
        )
        completed_cameras.add(camera_name)
        manifest["completed_cameras"] = sorted(completed_cameras)
        manifest["frame_counts"][camera_name] = frame_count
        write_json_atomic(manifest_path, manifest)

        center_m = [value * scale for value in camera["center_units"]]
        mamma_calibration[camera_name] = metric_calibration(camera, scale)
        records.append({
            "camera": camera_name,
            "source_camera_id": camera_id,
            "source_video": str(source),
            "center_rig_units": camera["center_units"],
            "center_metres": center_m,
        })

    write_json_atomic(calibration_path, mamma_calibration)
    capture = build_capture_descriptor(
        args.session, args.fps, list(mamma_calibration)
    )
    write_json_atomic(capture_path, capture)
    manifest["state"] = "complete"
    manifest["records"] = records
    write_json_atomic(manifest_path, manifest)
    print(f"Scale: {scale:.9f} metres per rig unit", flush=True)
    print(f"Wrote MAMMA capture: {capture_path}", flush=True)


if __name__ == "__main__":
    main()
