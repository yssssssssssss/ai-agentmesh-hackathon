"""
crop_screenshots.py — 把"总图"(多个手机截图拼一张大图)裁切成独立子图

用法:
    1. 修改 SOURCE 路径和 POSITIONS 列表
    2. python3 crop_screenshots.py
    3. 子图保存到 OUTPUT_DIR,JPEG 78% quality,宽度 480px

POSITIONS 标定方法:
    先用 Read 工具加载原图,根据 Claude 看到的视觉分割大致估算每张子图的 (x1, y1, x2, y2)
    再微调:第一张通常 x1 ≈ 图宽 × 0.04,每张约占图宽 1/N (N=屏幕数)
"""

from pathlib import Path
import base64
import os

from PIL import Image

SOURCE = os.getenv("PRD_SCREENSHOT_SOURCE", str(Path.cwd() / "screenshots.png"))
OUTPUT_DIR = os.getenv("PRD_ASSET_DIR", str(Path.cwd() / "prd-feasibility-assets"))
TARGET_WIDTH = 480  # 内嵌 HTML 用,~50KB/张
JPEG_QUALITY = 78

# 标定每个子图在总图中的位置: (name, x1, y1, x2, y2)
# x1/x2 是左右边界,y1/y2 是上下边界,单位:像素
POSITIONS = [
    # 示例:7 张手机截图横排,总宽 7384,每张 ~1055px,顶部 120px 留白
    ("01_homepage",  330,  120, 1185, 2100),
    ("02_popup",    1295,  120, 2145, 2100),
    ("03_panel",    2270,  120, 3120, 2100),
    ("04_cashout",  3255,  120, 4105, 2100),
    ("05_popup2",   4240,  120, 5090, 2100),
    ("06_success",  5220,  120, 6070, 2100),
    ("07_guide",    6190,  120, 7375, 2100),
]


def crop_and_compress():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    img = Image.open(SOURCE)
    print(f"原图尺寸: {img.size}")

    for name, x1, y1, x2, y2 in POSITIONS:
        crop = img.crop((x1, y1, x2, y2))
        # 保存原始 PNG(可选,留底用)
        crop.save(f"{OUTPUT_DIR}/{name}.png", optimize=True)
        # 压缩为 JPEG 用于 base64 内嵌
        rgb = crop.convert("RGB")
        w, h = rgb.size
        rgb.thumbnail((TARGET_WIDTH, TARGET_WIDTH * h // w), Image.LANCZOS)
        rgb.save(f"{OUTPUT_DIR}/{name}_jpg.jpg", "JPEG", quality=JPEG_QUALITY, optimize=True)
        size_kb = os.path.getsize(f"{OUTPUT_DIR}/{name}_jpg.jpg") / 1024
        print(f"  {name}: {crop.size} -> {rgb.size}, JPEG {size_kb:.1f} KB")


def build_base64_dict():
    """读取所有 _jpg.jpg 并返回 base64 字典(供 HTML 内嵌)"""
    imgs = {}
    for name, *_ in POSITIONS:
        path = f"{OUTPUT_DIR}/{name}_jpg.jpg"
        with open(path, "rb") as f:
            imgs[name] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    return imgs


if __name__ == "__main__":
    crop_and_compress()
    print(f"\n完成。子图保存至 {OUTPUT_DIR}/")
    print(f"使用 build_base64_dict() 获取 base64 字典")
