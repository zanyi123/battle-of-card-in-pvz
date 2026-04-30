"""scripts/process_plants.py - 批量处理植物图片，生成适配卡牌安全区的贴图。

使用方式：
  python scripts/process_plants.py

流程：
  1. 读取 assets/images/plants/ 下所有 PNG 图片
  2. 等比缩放至适应「插图安全区」（宽 60 × 高 80），居中粘贴到 80×120 透明画布
  3. 输出至 assets/cards/，文件名取原始文件名（与 cards.json image_file 对应）

安全区说明：
  - 最终卡牌尺寸 80×120，其中左上角 20×20 费用圈、右下角 20×20 攻击圈、
    底部 20px 名称条为 UI 覆盖层。插图安全区 = 中心 60×80，四周留白。
  - 输出文件名统一为小写（如 FA_04_huobao.png），与 cards.json 的 image_file 字段匹配。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根目录（scripts/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "assets" / "images" / "plants"
DST_DIR = PROJECT_ROOT / "assets" / "cards"

# 卡牌最终尺寸 & 插图安全区
CANVAS_W, CANVAS_H = 80, 120
SAFE_W, SAFE_H = 60, 80


def process_single(src_path: Path, dst_path: Path) -> bool:
    """处理单张图片：等比缩放 → 居中粘贴到透明画布。"""
    try:
        from PIL import Image
    except ImportError:
        print("[ERROR] Pillow 未安装，请运行: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    img = Image.open(src_path).convert("RGBA")
    orig_w, orig_h = img.size

    if orig_w == 0 or orig_h == 0:
        print(f"  [SKIP] {src_path.name}: 尺寸为零 ({orig_w}x{orig_h})")
        return False

    # 等比缩放至适应安全区（不拉伸）
    scale = min(SAFE_W / orig_w, SAFE_H / orig_h)
    new_w = max(1, int(orig_w * scale))
    new_h = max(1, int(orig_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # 创建透明画布
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))

    # 居中粘贴
    paste_x = (CANVAS_W - new_w) // 2
    paste_y = (CANVAS_H - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y))

    # 确保 dst 父目录存在
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst_path, "PNG")
    return True


def main() -> None:
    if not SRC_DIR.exists():
        print(f"[ERROR] 源目录不存在: {SRC_DIR}", file=sys.stderr)
        sys.exit(1)

    png_files = sorted(SRC_DIR.glob("*.png"))
    if not png_files:
        print(f"[WARN] {SRC_DIR} 下无 PNG 文件", file=sys.stderr)
        return

    DST_DIR.mkdir(parents=True, exist_ok=True)
    total = len(png_files)
    success = 0
    skipped = 0

    print(f"[process_plants] 开始处理: {total} 张图片")
    print(f"  源目录: {SRC_DIR}")
    print(f"  输出目录: {DST_DIR}")
    print(f"  安全区: {SAFE_W}x{SAFE_H}, 画布: {CANVAS_W}x{CANVAS_H}")

    for idx, src_path in enumerate(png_files, 1):
        # 文件名统一小写
        dst_name = src_path.name.lower()
        dst_path = DST_DIR / dst_name

        ok = process_single(src_path, dst_path)
        if ok:
            success += 1
            print(f"  [{idx}/{total}] OK: {src_path.name} -> {dst_name}")
        else:
            skipped += 1

    print(f"\n[process_plants] 完成: 成功 {success}, 跳过 {skipped}, 总计 {total}")


if __name__ == "__main__":
    main()
