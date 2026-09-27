"""S22 块 T：视觉回归比对引擎——确定性，无 LLM（宪法：判定全确定性）。

两级比对：
1. dHash（9×8 灰度差分哈希，64 位）初筛——汉明距离 ≤ HASH_MAX_DISTANCE 直接 pass；
2. 距离超限 → 像素级：逐像素通道差 > PIXEL_TOLERANCE 计差异像素，
   占比 ≤ DIFF_THRESHOLD pass。尺寸不同按基线缩放后比对并记 size_changed。

阈值经 config 环境变量配置（VISUAL_HASH_MAX_DISTANCE / VISUAL_PIXEL_TOLERANCE /
VISUAL_DIFF_THRESHOLD），私有化部署可调。
"""
from pathlib import Path

from PIL import Image

from app import config

HASH_MAX_DISTANCE = int(getattr(config, "VISUAL_HASH_MAX_DISTANCE", 4))
PIXEL_TOLERANCE = int(getattr(config, "VISUAL_PIXEL_TOLERANCE", 16))
DIFF_THRESHOLD = float(getattr(config, "VISUAL_DIFF_THRESHOLD", 0.02))


def dhash(image_path: str) -> int:
    """64 位差分哈希：缩到 9×8 灰度，相邻像素比较取位。"""
    with Image.open(image_path) as img:
        gray = img.convert("L").resize((9, 8))
    pixels = list(gray.get_flattened_data())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def compare_images(baseline_path: str, current_path: str) -> dict:
    """两级比对，返回判定与差异摘要（供断言 payload 与前端呈现）。"""
    result = {"passed": False, "hash_distance": None, "diff_ratio": None,
              "threshold": DIFF_THRESHOLD, "size_changed": False, "error": None}
    try:
        with Image.open(baseline_path) as b_img, Image.open(current_path) as c_img:
            if b_img.size != c_img.size:
                result["size_changed"] = True
                cur = c_img.convert("RGB").resize(b_img.size)
            else:
                cur = c_img.convert("RGB")
            base = b_img.convert("RGB")
    except Exception as exc:
        result["error"] = str(exc)[:200]
        return result

    result["hash_distance"] = _hamming(dhash(baseline_path), dhash(current_path))
    if result["hash_distance"] <= HASH_MAX_DISTANCE:
        result["passed"] = True
        result["diff_ratio"] = 0.0
        return result

    base_px, cur_px = base.load(), cur.load()
    w, h = base.size
    total = w * h
    differing = 0
    for y in range(h):
        for x in range(w):
            bp, cp = base_px[x, y], cur_px[x, y]
            if (abs(bp[0] - cp[0]) > PIXEL_TOLERANCE or
                    abs(bp[1] - cp[1]) > PIXEL_TOLERANCE or
                    abs(bp[2] - cp[2]) > PIXEL_TOLERANCE):
                differing += 1
    result["diff_ratio"] = round(differing / total, 6)
    result["passed"] = result["diff_ratio"] <= DIFF_THRESHOLD
    return result


def visual_dir(artifact_dir: str, skill_id: int) -> Path:
    return Path(artifact_dir) / "visual" / str(skill_id)
