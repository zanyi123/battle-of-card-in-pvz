"""utils/path_utils.py - PyInstaller 打包路径兼容工具。

解决打包后资源路径问题：
  - 开发模式：路径相对于项目根目录（当前工作目录）
  - 打包模式：路径相对于 sys._MEIPASS 临时解压目录

同时提供可写用户数据目录：
  - 开发模式：项目根目录
  - 打包模式：~/.pvz_card_game/（避免写权限问题）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_resource_path(relative_path: str) -> Path:
    """获取只读资源文件的绝对路径（兼容打包后）。

    Args:
        relative_path: 相对于项目根目录的路径，如 "assets/images/bg_menu.png"

    Returns:
        解析后的绝对路径
    """
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller 单文件模式：资源解压到临时目录
        base_path = Path(sys._MEIPASS)
    else:
        # 开发模式：使用项目根目录
        base_path = Path(os.path.abspath("."))
    return base_path / relative_path


def get_user_data_dir() -> Path:
    """获取可写用户数据目录。

    打包模式下使用用户主目录下的专用文件夹，避免写权限问题。
    开发模式下直接使用项目根目录。

    Returns:
        可写目录路径（自动创建）
    """
    if hasattr(sys, "_MEIPASS"):
        data_dir = Path(os.path.expanduser("~")) / ".pvz_card_game"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    return Path(os.path.abspath("."))


def get_save_data_path() -> Path:
    """获取 save_data.json 文件路径。"""
    return get_user_data_dir() / "save_data.json"


def get_settings_path() -> Path:
    """获取 settings.json 文件路径。"""
    return get_user_data_dir() / "settings.json"
