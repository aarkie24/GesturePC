"""Generates deterministic synthetic hand landmark fixtures for reproducible tests."""

from __future__ import annotations

from typing import Dict, List, Tuple
import numpy as np

# Canonical 21 landmark topology:
# 0: Wrist
# 1-4: Thumb (CMC, MCP, IP, TIP)
# 5-8: Index (MCP, PIP, DIP, TIP)
# 9-12: Middle (MCP, PIP, DIP, TIP)
# 13-16: Ring (MCP, PIP, DIP, TIP)
# 17-20: Pinky (MCP, PIP, DIP, TIP)


def _base_palm_landmarks() -> np.ndarray:
    """Returns canonical open palm metric world landmarks (shape (21, 3))."""
    lm = np.zeros((21, 3), dtype=np.float32)

    # 0: Wrist at origin
    lm[0] = [0.0, 0.0, 0.0]

    # Thumb
    lm[1] = [-0.03, 0.02, 0.0]
    lm[2] = [-0.05, 0.05, 0.0]
    lm[3] = [-0.07, 0.08, 0.0]
    lm[4] = [-0.09, 0.11, 0.0]  # Tip

    # Index
    lm[5] = [-0.03, 0.09, 0.0]
    lm[6] = [-0.03, 0.13, 0.0]
    lm[7] = [-0.03, 0.16, 0.0]
    lm[8] = [-0.03, 0.19, 0.0]  # Tip

    # Middle (Palm unit reference: L9 is middle MCP)
    lm[9] = [0.0, 0.10, 0.0]
    lm[10] = [0.0, 0.15, 0.0]
    lm[11] = [0.0, 0.18, 0.0]
    lm[12] = [0.0, 0.21, 0.0]  # Tip

    # Ring
    lm[13] = [0.03, 0.09, 0.0]
    lm[14] = [0.03, 0.13, 0.0]
    lm[15] = [0.03, 0.16, 0.0]
    lm[16] = [0.03, 0.18, 0.0]  # Tip

    # Pinky
    lm[17] = [0.05, 0.07, 0.0]
    lm[18] = [0.06, 0.10, 0.0]
    lm[19] = [0.07, 0.13, 0.0]
    lm[20] = [0.08, 0.15, 0.0]  # Tip

    return lm


def generate_pose_landmarks(
    pose_name: str,
    noise_sigma: float = 0.0,
    wrist_translation: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
    seed: Optional[int] = None,
) -> np.ndarray:
    """Generates synthetic (21, 3) metric landmarks for a named pose.
    
    Supported poses:
    - 'open_palm': All 5 fingers extended flat.
    - 'fist': All fingers curled inward toward palm.
    - 'peace' / 'victory': Index & middle extended, others curled.
    - 'thumbs_up': Thumb pointing upward, other 4 fingers curled.
    """
    if seed is not None:
        np.random.seed(seed)

    lm = _base_palm_landmarks()

    if pose_name.lower() in ("fist", "closed_fist"):
        # Curl all fingertips toward MCP
        # Thumb
        lm[3] = [-0.02, 0.05, 0.02]
        lm[4] = [-0.01, 0.04, 0.02]
        # Index
        lm[7] = [-0.03, 0.08, 0.02]
        lm[8] = [-0.03, 0.07, 0.02]
        # Middle
        lm[11] = [0.0, 0.09, 0.02]
        lm[12] = [0.0, 0.08, 0.02]
        # Ring
        lm[15] = [0.03, 0.08, 0.02]
        lm[16] = [0.03, 0.07, 0.02]
        # Pinky
        lm[19] = [0.06, 0.06, 0.02]
        lm[20] = [0.06, 0.05, 0.02]

    elif pose_name.lower() in ("peace", "victory"):
        # Curl thumb, ring, pinky; keep index & middle extended
        lm[3] = [-0.02, 0.05, 0.02]
        lm[4] = [-0.01, 0.04, 0.02]
        lm[15] = [0.03, 0.08, 0.02]
        lm[16] = [0.03, 0.07, 0.02]
        lm[19] = [0.06, 0.06, 0.02]
        lm[20] = [0.06, 0.05, 0.02]

    elif pose_name.lower() in ("thumbs_up", "thumb_up"):
        # Thumb points straight up, others curled
        lm[2] = [-0.01, 0.05, 0.0]
        lm[3] = [-0.01, 0.10, 0.0]
        lm[4] = [-0.01, 0.15, 0.0]
        # Curl 4 fingers
        lm[7] = [-0.03, 0.08, 0.02]
        lm[8] = [-0.03, 0.07, 0.02]
        lm[11] = [0.0, 0.09, 0.02]
        lm[12] = [0.0, 0.08, 0.02]
        lm[15] = [0.03, 0.08, 0.02]
        lm[16] = [0.03, 0.07, 0.02]
        lm[19] = [0.06, 0.06, 0.02]
        lm[20] = [0.06, 0.05, 0.02]

    # Apply scaling
    lm *= scale

    # Apply wrist translation
    lm += np.array(wrist_translation, dtype=np.float32)

    # Add noise
    if noise_sigma > 0.0:
        noise = np.random.normal(0.0, noise_sigma, lm.shape).astype(np.float32)
        lm += noise

    return lm.astype(np.float32)


def generate_fixture_sequence(
    pose_name: str,
    num_frames: int = 30,
    noise_sigma: float = 0.002,
    fps: float = 30.0,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generates a sequence of frames for a static pose.
    
    Returns:
        (landmarks_world, landmarks_image, timestamps_ns)
        where landmarks_world is shape (num_frames, 21, 3),
        landmarks_image is shape (num_frames, 21, 3),
        timestamps_ns is shape (num_frames,)
    """
    np.random.seed(seed)
    world_frames = np.zeros((num_frames, 21, 3), dtype=np.float32)
    img_frames = np.zeros((num_frames, 21, 3), dtype=np.float32)
    timestamps = np.zeros((num_frames,), dtype=np.int64)

    dt_ns = int(1e9 / fps)
    start_ts = 1_000_000_000_000

    base_world = generate_pose_landmarks(pose_name, noise_sigma=0.0)

    for i in range(num_frames):
        ts = start_ts + i * dt_ns
        timestamps[i] = ts

        # World landmarks with small temporal noise
        noise = np.random.normal(0.0, noise_sigma, (21, 3)).astype(np.float32)
        noise[0] *= 0.1  # Wrist position is held steady during a static pose
        wf = (base_world + noise).astype(np.float32)
        world_frames[i] = wf

        # Image landmarks projected to [0.3..0.7] coordinate box
        img_f = wf.copy()
        img_f[:, 0] = (img_f[:, 0] + 0.15) * 1.5 + 0.35
        img_f[:, 1] = (img_f[:, 1] + 0.15) * 1.5 + 0.35
        img_frames[i] = img_f

    return world_frames, img_frames, timestamps
