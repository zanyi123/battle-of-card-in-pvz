"""build.py - PVZ 植物卡牌对战 PyInstaller 打包脚本。

用法：
    python build.py              # 默认打包（单文件 + 无控制台）
    python build.py --debug      # 打包并保留控制台（用于调试）

依赖：
    pip install pyinstaller

输出：
    dist/PVZ_Plant_Card_Game.exe  （单文件可执行程序）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── 项目根目录 ───────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def _generate_icon() -> Path | None:
    """尝试从 assets/images 生成 .ico 图标文件。

    如果 assets/images 下有合适的图片（优先 png/jpg），就用 Pillow 生成 .ico。
    如果 Pillow 不可用或没有合适图片，返回 None（build.py 不使用 --icon）。
    """
    icon_path = PROJECT_ROOT / "assets" / "icon.ico"
    if icon_path.exists():
        return icon_path

    # 候选源图片（按优先级排序）
    candidates: list[Path] = [
        PROJECT_ROOT / "assets" / "images" / "bg_menu.png",
        PROJECT_ROOT / "assets" / "images" / "bg_garden.png",
    ]

    source: Path | None = None
    for c in candidates:
        if c.exists():
            source = c
            break

    if source is None:
        return None

    try:
        from PIL import Image  # type: ignore[import-untyped]

        img = Image.open(str(source))
        img = img.resize((256, 256), Image.Resampling.LANCZOS)
        img.save(str(icon_path), format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
        print(f"[build] 生成图标: {icon_path}")
        return icon_path
    except ImportError:
        print("[build] Pillow 未安装，跳过图标生成。可运行: pip install Pillow")
        return None
    except Exception as exc:
        print(f"[build] 图标生成失败: {exc}")
        return None


def _collect_datas() -> list[str]:
    """收集需要打包的数据文件（PyInstaller --add-data 格式）。

    返回 ["src_path;dst_path", ...] 列表。
    """
    datas: list[str] = []

    # 1. assets 目录（整个打包）
    assets_root = PROJECT_ROOT / "assets"
    if assets_root.exists():
        datas.append(f"{assets_root};assets")

    # 2. config 目录（cards.json）
    config_root = PROJECT_ROOT / "config"
    if config_root.exists():
        datas.append(f"{config_root};config")

    # 3. 默认配置文件（首次运行时复制到用户目录）
    for fname in ("save_data.json", "settings.json"):
        fpath = PROJECT_ROOT / fname
        if fpath.exists():
            datas.append(f"{fpath};.")

    return datas


def _collect_hiddenimports() -> list[str]:
    """收集需要显式声明的隐藏导入模块。"""
    return [
        "core.event_bus",
        "core.input_router",
        "core.models",
        "core.music_manager",
        "core.settings_manager",
        "core.state_machine",
        "core.save_manager",
        "core.resolution_engine",
        "core.effect_registry",
        "core.skill_registry",
        "core.effect_executor",
        "core.effects",
        "core.pure_loop",
        "ui.intro_screen",
        "ui.loading_screen",
        "ui.main_menu",
        "ui.confirm_dialog",
        "ui.order_dialog",
        "ui.renderer",
        "ui.asset_manager",
        "ui.notification_panel",
        "ui.floating_text",
        "ui.card_renderer",
        "utils.path_utils",
    ]


def build(debug: bool = False) -> None:
    """执行 PyInstaller 打包。

    Args:
        debug: 如果为 True，保留控制台窗口（用于调试）
    """
    print("=" * 60)
    print("  PVZ 植物卡牌对战 - PyInstaller 打包工具")
    print("=" * 60)

    # ── 检查 PyInstaller ──────────────────────────────────────────
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("\n[错误] PyInstaller 未安装！")
        print("请先运行: pip install pyinstaller")
        sys.exit(1)

    # ── 清理旧构建 ────────────────────────────────────────────────
    if BUILD_DIR.exists():
        print(f"[build] 清理旧构建目录: {BUILD_DIR}")
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    if DIST_DIR.exists():
        print(f"[build] 清理旧输出目录: {DIST_DIR}")
        shutil.rmtree(DIST_DIR, ignore_errors=True)

    # ── 生成图标 ──────────────────────────────────────────────────
    icon = _generate_icon()

    # ── 收集资源 ──────────────────────────────────────────────────
    datas = _collect_datas()
    hiddenimports = _collect_hiddenimports()

    print(f"\n[build] 数据文件 ({len(datas)} 项):")
    for d in datas:
        print(f"  + {d}")
    print(f"\n[build] 隐藏导入 ({len(hiddenimports)} 项)")

    # ── 构建 PyInstaller 命令 ─────────────────────────────────────
    cmd: list[str] = [
        sys.executable, "-m", "PyInstaller",
        "--name", "PVZ_Plant_Card_Game",
        "--onefile",
        "--clean",
        "--noconfirm",
    ]

    # 调试模式保留控制台，发布模式隐藏
    if not debug:
        cmd.append("--noconsole")

    # 图标
    if icon is not None:
        cmd.extend(["--icon", str(icon)])

    # 数据文件
    for d in datas:
        cmd.extend(["--add-data", d])

    # 隐藏导入
    for h in hiddenimports:
        cmd.extend(["--hidden-import", h])

    # 入口脚本
    cmd.append(str(PROJECT_ROOT / "main.py"))

    # ── 执行打包 ──────────────────────────────────────────────────
    print(f"\n[build] 执行打包命令:")
    print(f"  {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print(f"\n[错误] 打包失败，退出码: {result.returncode}")
        sys.exit(1)

    # ── 输出结果 ──────────────────────────────────────────────────
    exe_path = DIST_DIR / "PVZ_Plant_Card_Game.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n{'=' * 60}")
        print(f"  打包成功!")
        print(f"  输出: {exe_path}")
        print(f"  大小: {size_mb:.1f} MB")
        print(f"{'=' * 60}")
    else:
        print(f"\n[警告] 打包完成但未找到输出文件: {exe_path}")
        print(f"  请检查 dist/ 目录")


def main() -> None:
    debug = "--debug" in sys.argv
    build(debug=debug)


if __name__ == "__main__":
    main()
