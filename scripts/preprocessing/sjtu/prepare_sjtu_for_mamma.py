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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("session")
    parser.add_argument("--camera-ids", nargs="+", type=int, default=list(range(12)))
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Clip duration in seconds; omit to encode through the source end.",
    )
    parser.add_argument(
        "--fps",
        type=positive_integer,
        default=25,
        help="Positive integral frame rate (the current MAMMA capture path stores an integer).",
    )
    parser.add_argument("--adjacent-spacing-metres", type=float, default=0.46)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def mat_vec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[j] * vector[j] for j in range(3)) for row in matrix]


def parse_calibration(path: Path) -> dict[int, dict]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) % 5:
        raise ValueError(f"{path} does not contain five lines per camera")
    cameras: dict[int, dict] = {}
    for offset in range(0, len(lines), 5):
        camera_id = int(lines[offset].split()[1])
        width, height = map(int, lines[offset + 1].split()[1:])
        fx, fy, cx, cy = map(float, lines[offset + 2].split()[1:])
        r_values = list(map(float, lines[offset + 3].split()[1:]))
        center = list(map(float, lines[offset + 4].split()[1:]))
        if len(r_values) != 9 or len(center) != 3:
            raise ValueError(f"Invalid calibration block for camera {camera_id}")
        rotation = [r_values[row * 3 : (row + 1) * 3] for row in range(3)]
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
    overwrite: bool,
) -> list[tuple[int, str, Path, Path]]:
    jobs = []
    missing_sources = []
    existing_outputs = []
    for camera_id in camera_ids:
        source = dataset_root / "RGB" / f"{camera_id}.mp4"
        camera_name = f"cam_{camera_id:02d}"
        output = videos_dir / f"{camera_name}.mp4"
        if not source.is_file():
            missing_sources.append(source)
        if output.exists() and not overwrite:
            existing_outputs.append(output)
        jobs.append((camera_id, camera_name, source, output))

    if missing_sources:
        paths = "\n".join(f"- {path}" for path in missing_sources)
        raise FileNotFoundError(f"Missing source videos:\n{paths}")
    if existing_outputs:
        paths = "\n".join(f"- {path}" for path in existing_outputs)
        raise FileExistsError(
            f"Refusing to overwrite existing outputs; pass --overwrite:\n{paths}"
        )
    return jobs


def main() -> None:
    args = parse_args()
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
            dataset_root, videos_dir, args.camera_ids, args.overwrite
        )
    except (FileNotFoundError, FileExistsError) as exc:
        raise SystemExit(str(exc)) from exc
    mamma_calibration: dict[str, dict] = {}
    records = []

    for camera_id, camera_name, source, output in video_jobs:
        video_filter = f"trim=start={args.start_seconds}"
        if args.duration is not None:
            video_filter += f":duration={args.duration}"
        video_filter += f",setpts=PTS-STARTPTS,fps={args.fps}"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-y" if args.overwrite else "-n", "-i", str(source), "-an",
            "-vf", video_filter, "-c:v", "libx264", "-preset", "fast",
            "-crf", "18", "-pix_fmt", "yuv420p", str(output),
        ]
        print(f"Encoding source camera {camera_id} as {camera_name}", flush=True)
        subprocess.run(command, check=True)

        camera = cameras[camera_id]
        center_m = [value * scale for value in camera["center_units"]]
        mamma_calibration[camera_name] = metric_calibration(camera, scale)
        records.append({
            "camera": camera_name,
            "source_camera_id": camera_id,
            "source_video": str(source),
            "center_rig_units": camera["center_units"],
            "center_metres": center_m,
        })

    calibration_path = session_dir / "calibration.json"
    calibration_path.write_text(json.dumps(mamma_calibration, indent=2) + "\n")
    capture = {
        "capture_root": str(args.output_root.resolve()),
        "calib": str(calibration_path),
        "cam_fps": args.fps,
        "videos_subdir": "videos",
        "cams": list(mamma_calibration),
        "sequences": {"000": {"name": args.session}},
    }
    capture_path = session_dir / "capture.json"
    capture_path.write_text(json.dumps(capture, indent=2) + "\n")
    manifest = {
        "source": str(dataset_root),
        "start_seconds": args.start_seconds,
        "duration_seconds": args.duration,
        "fps": args.fps,
        "camera_order": args.camera_ids,
        "calibration_convention": "Xc = R @ Xw + (-R @ C_metres)",
        "adjacent_spacing_metres": args.adjacent_spacing_metres,
        "adjacent_distances_rig_units": adjacent_distances,
        "median_adjacent_spacing_rig_units": median_spacing_units,
        "metres_per_rig_unit": scale,
        "records": records,
    }
    (session_dir / "conformance.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(f"Scale: {scale:.9f} metres per rig unit", flush=True)
    print(f"Wrote MAMMA capture: {capture_path}", flush=True)


if __name__ == "__main__":
    main()
