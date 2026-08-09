#!/usr/bin/env python3
"""Render a shareable MAMMA reconstruction with a camera filmstrip.

The main panel is an upright, stabilized virtual-camera render of the SMPL-X
reconstruction. Synchronized source views are letterboxed into a filmstrip at
the bottom. SJTU world coordinates are X-up and are converted to a conventional
Y-up display coordinate system before rendering.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import cv2
import numpy as np
import pyrender
import trimesh


CANVAS_W = 1920
CANVAS_H = 1080
STRIP_H = 216
MAIN_H = CANVAS_H - STRIP_H
PERSON_COLORS = ((255, 91, 82), (70, 211, 255), (119, 231, 160))
DEFAULT_FACES = Path(__file__).resolve().parents[1] / "visualization/assets/smplx_faces.npy"


def positive_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ma-3d-dir", required=True, type=Path)
    parser.add_argument("--videos-dir", required=True, type=Path)
    parser.add_argument("--faces", type=Path, default=DEFAULT_FACES)
    parser.add_argument("--cams", nargs="+", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--fps", type=positive_finite_float, default=25.0)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument(
        "--source-start-frame",
        type=int,
        default=0,
        help=(
            "Source-video frame corresponding to reconstructed mesh frame 0. "
            "Set this to the pipeline's global.start_frame for sliced runs."
        ),
    )
    return parser.parse_args()


def world_to_display(vertices: np.ndarray) -> np.ndarray:
    """Convert SJTU X-up world coordinates to right-handed Y-up display space."""
    # display X <- world Z, display Y <- world X, display Z <- world Y
    return vertices[..., [2, 0, 1]].astype(np.float32, copy=False)


def moving_average(values: np.ndarray, radius: int = 18) -> np.ndarray:
    if radius <= 0 or len(values) < 3:
        return values.copy()
    padded = np.pad(values, ((radius, radius), (0, 0)), mode="edge")
    kernel = np.ones(2 * radius + 1, dtype=np.float64) / (2 * radius + 1)
    return np.stack(
        [
            np.convolve(padded[:, axis], kernel, mode="valid")
            for axis in range(values.shape[1])
        ],
        axis=1,
    ).astype(np.float32)


def load_motions(ma_3d_dir: Path) -> list[np.ndarray]:
    files = sorted(ma_3d_dir.glob("verts_joints_body_id-*.npz"))
    if not files:
        raise FileNotFoundError(f"No reconstructed bodies found under {ma_3d_dir}")
    motions = []
    for path in files:
        with np.load(path) as data:
            motions.append(world_to_display(data["pred_vertices"]))
    frame_counts = {len(motion) for motion in motions}
    if len(frame_counts) != 1:
        raise ValueError(f"Body frame counts disagree: {sorted(frame_counts)}")
    return motions


def look_at_pose(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward /= np.linalg.norm(forward)
    backward = -forward
    right = np.cross(np.array([0.0, 1.0, 0.0]), backward)
    right /= np.linalg.norm(right)
    up = np.cross(backward, right)
    pose = np.eye(4, dtype=np.float32)
    pose[:3, 0] = right
    pose[:3, 1] = up
    pose[:3, 2] = backward
    pose[:3, 3] = eye
    return pose


def material(rgb: tuple[int, int, int]) -> pyrender.MetallicRoughnessMaterial:
    color = tuple(channel / 255.0 for channel in rgb) + (1.0,)
    return pyrender.MetallicRoughnessMaterial(
        baseColorFactor=color,
        metallicFactor=0.05,
        roughnessFactor=0.72,
    )


def add_ground(
    scene: pyrender.Scene, center: np.ndarray, floor_y: float, span: float
) -> None:
    plane = trimesh.creation.box(extents=(span, 0.025, span))
    plane.apply_translation((center[0], floor_y - 0.02, center[2]))
    scene.add(
        pyrender.Mesh.from_trimesh(
            plane, material=material((27, 35, 42)), smooth=False
        )
    )

    grid_color = material((48, 83, 91))
    half = span / 2
    for offset in np.arange(-half, half + 0.001, 1.0):
        line_x = trimesh.creation.box(extents=(span, 0.008, 0.012))
        line_x.apply_translation((center[0], floor_y, center[2] + offset))
        scene.add(
            pyrender.Mesh.from_trimesh(line_x, material=grid_color, smooth=False)
        )
        line_z = trimesh.creation.box(extents=(0.012, 0.008, span))
        line_z.apply_translation((center[0] + offset, floor_y, center[2]))
        scene.add(
            pyrender.Mesh.from_trimesh(line_z, material=grid_color, smooth=False)
        )


def frame_geometry(
    motions: list[np.ndarray],
) -> tuple[np.ndarray, float, float, float, float]:
    n_frames = len(motions[0])
    centers = np.empty((n_frames, 3), dtype=np.float32)
    spans = np.empty((n_frames, 3), dtype=np.float32)
    for frame in range(n_frames):
        mins = np.min([motion[frame].min(axis=0) for motion in motions], axis=0)
        maxs = np.max([motion[frame].max(axis=0) for motion in motions], axis=0)
        centers[frame] = (mins + maxs) / 2
        spans[frame] = maxs - mins
    centers = moving_average(centers)
    floor_y = float(
        np.percentile(
            np.concatenate([motion[:, :, 1].min(axis=1) for motion in motions]),
            5,
        )
    )
    camera_distance = max(
        6.0,
        float(np.percentile(spans[:, 1], 99)) / (2 * np.tan(np.deg2rad(21))),
        float(np.percentile(spans[:, 0], 99))
        / (2 * np.tan(np.deg2rad(21)) * (CANVAS_W / MAIN_H)),
    ) * 1.28
    ground_span = max(
        12.0,
        float(np.ptp(centers[:, 0])) + 10.0,
        float(np.ptp(centers[:, 2])) + 10.0,
    )
    ground_span_per_frame = np.linalg.norm(spans[:, [0, 2]], axis=1)
    ortho_ymag = max(
        1.32,
        float(np.percentile(spans[:, 1], 99)) * 0.64,
        float(np.percentile(ground_span_per_frame, 99))
        / (2 * (CANVAS_W / MAIN_H))
        * 1.20,
    )
    return centers, floor_y, camera_distance, ground_span, ortho_ymag


def fit_letterbox(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    canvas = np.full((height, width, 3), 18, dtype=np.uint8)
    if frame is None or frame.size == 0:
        return canvas
    scale = min(width / frame.shape[1], height / frame.shape[0])
    resized = cv2.resize(
        frame,
        (
            max(1, round(frame.shape[1] * scale)),
            max(1, round(frame.shape[0] * scale)),
        ),
        interpolation=cv2.INTER_AREA,
    )
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return canvas


def validate_source_fps(
    camera: str,
    actual_fps: float,
    requested_fps: float,
    reference_fps: float | None,
) -> None:
    tolerance = {"rel_tol": 1e-4, "abs_tol": 1e-2}
    if not math.isfinite(actual_fps) or actual_fps <= 0:
        raise ValueError(f"{camera} reports invalid source FPS {actual_fps}")
    if not math.isclose(actual_fps, requested_fps, **tolerance):
        raise ValueError(
            f"{camera} source FPS {actual_fps:.6g} does not match "
            f"requested render FPS {requested_fps:.6g}"
        )
    if reference_fps is not None and not math.isclose(
        actual_fps, reference_fps, **tolerance
    ):
        raise ValueError(
            f"{camera} source FPS {actual_fps:.6g} does not match "
            f"the first camera FPS {reference_fps:.6g}"
        )


def seek_capture(capture: cv2.VideoCapture, camera: str, frame: int) -> None:
    if frame == 0:
        return
    if not capture.set(cv2.CAP_PROP_POS_FRAMES, frame):
        raise RuntimeError(f"{camera} could not seek to source frame {frame}")
    actual_frame = capture.get(cv2.CAP_PROP_POS_FRAMES)
    if not math.isfinite(actual_frame) or abs(actual_frame - frame) > 0.5:
        raise RuntimeError(
            f"{camera} sought to source frame {actual_frame:g}; expected {frame}"
        )


def label(
    frame: np.ndarray,
    text: str,
    origin: tuple[int, int],
    scale: float = 0.62,
    color: tuple[int, int, int] = (245, 245, 245),
) -> None:
    x, y = origin
    cv2.putText(
        frame, text, (x + 2, y + 2), cv2.FONT_HERSHEY_SIMPLEX,
        scale, (0, 0, 0), 4, cv2.LINE_AA,
    )
    cv2.putText(
        frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
        scale, color, 1, cv2.LINE_AA,
    )


def main() -> int:
    args = parse_args()
    motions = load_motions(args.ma_3d_dir)
    faces = np.load(args.faces).astype(np.int32)
    total_frames = len(motions[0])
    start = max(0, args.start_frame)
    if args.source_start_frame < 0:
        raise ValueError("--source-start-frame must be non-negative")
    end = total_frames if args.max_frames is None else min(
        total_frames, start + args.max_frames
    )
    if start >= end:
        raise ValueError(f"Empty frame range: {start}:{end} of {total_frames}")

    selected_motions = [motion[start:end] for motion in motions]
    centers, floor_y, camera_distance, ground_span, ortho_ymag = frame_geometry(
        selected_motions
    )
    world_center = np.median(centers, axis=0)
    scene = pyrender.Scene(
        bg_color=(15, 20, 25, 255), ambient_light=(0.52, 0.52, 0.52)
    )
    add_ground(scene, world_center, floor_y, ground_span)
    camera = pyrender.OrthographicCamera(
        xmag=ortho_ymag * (CANVAS_W / MAIN_H), ymag=ortho_ymag
    )
    camera_node = scene.add(camera, pose=np.eye(4))
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.2)
    light_node = scene.add(light, pose=np.eye(4))
    fill = pyrender.DirectionalLight(
        color=np.array([0.72, 0.82, 1.0]), intensity=1.6
    )
    scene.add(
        fill,
        pose=look_at_pose(
            world_center + np.array([-5.0, 7.0, 4.0]), world_center
        ),
    )
    body_nodes = [
        scene.add(
            pyrender.Mesh.from_trimesh(
                trimesh.Trimesh(motion[start], faces, process=False),
                material=material(PERSON_COLORS[index % len(PERSON_COLORS)]),
                smooth=True,
            )
        )
        for index, motion in enumerate(motions)
    ]
    renderer = pyrender.OffscreenRenderer(CANVAS_W, MAIN_H)

    captures = []
    reference_fps = None
    try:
        for cam in args.cams:
            path = args.videos_dir / f"{cam}.mp4"
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                capture.release()
                raise FileNotFoundError(f"Could not open camera video: {path}")
            captures.append(capture)
            actual_fps = capture.get(cv2.CAP_PROP_FPS)
            validate_source_fps(cam, actual_fps, args.fps, reference_fps)
            if reference_fps is None:
                reference_fps = actual_fps
            seek_capture(
                capture,
                cam,
                args.source_start_frame + start,
            )
    except BaseException:
        for capture in captures:
            capture.release()
        renderer.delete()
        raise

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.output.with_name(
        f".{args.output.stem}.partial{args.output.suffix}"
    )
    temporary_output.unlink(missing_ok=True)
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{CANVAS_W}x{CANVAS_H}", "-r", str(args.fps), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(temporary_output),
        ],
        stdin=subprocess.PIPE,
    )

    try:
        try:
            slot_w = CANVAS_W // len(captures)
            for frame_number in range(start, end):
                local_frame = frame_number - start
                target = centers[local_frame].copy()
                target[1] = max(target[1], floor_y + 0.9)
                eye = target + np.array(
                    [camera_distance * 0.48, camera_distance * 0.18, camera_distance],
                    dtype=np.float32,
                )
                pose = look_at_pose(eye, target)
                scene.set_pose(camera_node, pose)
                scene.set_pose(light_node, pose)

                for body_index, node in enumerate(body_nodes):
                    mesh = trimesh.Trimesh(
                        motions[body_index][frame_number], faces, process=False
                    )
                    node.mesh = pyrender.Mesh.from_trimesh(
                        mesh,
                        material=material(
                            PERSON_COLORS[body_index % len(PERSON_COLORS)]
                        ),
                        smooth=True,
                    )

                rgb, _ = renderer.render(
                    scene,
                    flags=pyrender.RenderFlags.RGBA
                    | pyrender.RenderFlags.SHADOWS_DIRECTIONAL,
                )
                canvas = np.full((CANVAS_H, CANVAS_W, 3), 16, dtype=np.uint8)
                canvas[:MAIN_H] = cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2BGR)
                cv2.rectangle(
                    canvas, (0, MAIN_H), (CANVAS_W, CANVAS_H), (12, 12, 14), -1
                )

                for index, (cam, capture) in enumerate(zip(args.cams, captures)):
                    ok, source = capture.read()
                    if not ok:
                        source_frame = args.source_start_frame + frame_number
                        raise RuntimeError(
                            f"Failed to read {cam} at source frame {source_frame}"
                        )
                    thumb_h = min(STRIP_H, round(slot_w * 9 / 16))
                    thumb = fit_letterbox(source, slot_w, thumb_h)
                    x0 = index * slot_w
                    y0 = MAIN_H + (STRIP_H - thumb_h) // 2
                    canvas[y0 : y0 + thumb_h, x0 : x0 + slot_w] = thumb
                    cv2.rectangle(
                        canvas,
                        (x0, y0),
                        (x0 + slot_w - 1, y0 + thumb_h - 1),
                        (68, 68, 72),
                        1,
                    )
                    label(
                        canvas,
                        cam.replace("cam_", "CAM "),
                        (x0 + 10, y0 + 24),
                        0.52,
                    )

                cv2.rectangle(canvas, (0, 0), (CANVAS_W, 62), (15, 20, 25), -1)
                cv2.putText(
                    canvas, args.title, (34, 41), cv2.FONT_HERSHEY_SIMPLEX,
                    0.92, (238, 242, 246), 2, cv2.LINE_AA,
                )
                source_frame = args.source_start_frame + frame_number
                time_text = (
                    f"{(source_frame / args.fps):05.2f}s  |  {len(args.cams)} views"
                )
                size, _ = cv2.getTextSize(
                    time_text, cv2.FONT_HERSHEY_SIMPLEX, 0.68, 1
                )
                cv2.putText(
                    canvas, time_text, (CANVAS_W - size[0] - 34, 39),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, (168, 179, 189),
                    1, cv2.LINE_AA,
                )

                assert ffmpeg.stdin is not None
                ffmpeg.stdin.write(canvas.tobytes())
                rendered = frame_number - start + 1
                if rendered % 50 == 0 or frame_number + 1 == end:
                    print(f"rendered {rendered}/{end - start}", flush=True)
        finally:
            for capture in captures:
                capture.release()
            renderer.delete()
            if ffmpeg.stdin is not None and not ffmpeg.stdin.closed:
                ffmpeg.stdin.close()

        return_code = ffmpeg.wait()
        if return_code:
            raise RuntimeError(f"ffmpeg exited with status {return_code}")
        temporary_output.replace(args.output)
    except BaseException:
        if ffmpeg.stdin is not None and not ffmpeg.stdin.closed:
            ffmpeg.stdin.close()
        if ffmpeg.poll() is None:
            ffmpeg.wait()
        temporary_output.unlink(missing_ok=True)
        raise
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
