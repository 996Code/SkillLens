"""S22 块 T：视觉比对引擎（TDD 先红）——确定性，无 LLM。

覆盖：dHash 同图/异图距离、compare_images 两级判定（哈希初筛/像素占比）、
阈值边界、尺寸变化缩放比对。
"""
import pytest

from app.replay.visual import compare_images, dhash


def _png(path, size=(100, 100), color=(200, 200, 200), patch=None, gradient=False):
    """生成测试 PNG：纯色/渐变底 + 可选矩形补丁 (x, y, w, h, color)。"""
    from PIL import Image
    if gradient:
        import random
        rng = random.Random(42)
        img = Image.new("RGB", size)
        px = img.load()
        for x in range(size[0]):
            for y in range(size[1]):
                px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    else:
        img = Image.new("RGB", size, color)
    if patch:
        x, y, w, h, c = patch
        for i in range(x, min(x + w, size[0])):
            for j in range(y, min(y + h, size[1])):
                img.putpixel((i, j), c)
    img.save(path)
    return str(path)


def test_dhash_identical_images_distance_zero(tmp_path):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")
    assert dhash(a) == dhash(b)


def test_dhash_different_images_distance_large(tmp_path):
    # 纯色图 dHash 全零（均匀无梯度）——用渐变图测区分度
    a = _png(tmp_path / "a.png", gradient=True)
    b = _png(tmp_path / "b.png", color=(20, 20, 20))
    ha, hb = dhash(a), dhash(b)
    assert bin(ha ^ hb).count("1") > 4


def test_compare_identical_passes(tmp_path):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")
    r = compare_images(a, b)
    assert r["passed"] is True
    assert r["hash_distance"] == 0
    assert r["diff_ratio"] == 0.0


def test_compare_small_patch_within_threshold_passes(tmp_path):
    # 100x100=1 万像素，10x10=100 像素补丁 = 1% < 2% 阈值 → pass
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png", patch=(0, 0, 10, 10, (0, 0, 0)))
    r = compare_images(a, b)
    assert r["passed"] is True
    # 初筛短路时 diff_ratio=0.0；像素路径时 ≤2%
    assert r["diff_ratio"] is not None and r["diff_ratio"] <= 0.02


def test_compare_large_patch_exceeds_threshold_fails(tmp_path):
    # 40x40=1600 像素 = 16% > 2% → fail
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png", patch=(0, 0, 40, 40, (0, 0, 0)))
    r = compare_images(a, b)
    assert r["passed"] is False
    assert r["diff_ratio"] > 0.02


def test_compare_size_change_resized_and_flagged(tmp_path):
    # 尺寸不同：按基线缩放比对（内容一致 → pass），并记录 size_changed
    a = _png(tmp_path / "a.png", size=(100, 100))
    b = _png(tmp_path / "b.png", size=(200, 200))
    r = compare_images(a, b)
    assert r["size_changed"] is True
    assert r["passed"] is True


def test_compare_threshold_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr("app.replay.visual.HASH_MAX_DISTANCE", -1)  # 强制像素路径
    monkeypatch.setattr("app.replay.visual.DIFF_THRESHOLD", 0.001)
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png", patch=(0, 0, 5, 5, (0, 0, 0)))
    assert compare_images(a, b)["passed"] is False


def test_compare_missing_file_returns_error(tmp_path):
    r = compare_images(str(tmp_path / "nope.png"), str(tmp_path / "nope2.png"))
    assert r["passed"] is False
    assert r.get("error")
