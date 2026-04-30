"""core/settings_manager.py - 游戏设置管理器。

持久化字段（settings.json）：
  - bgm_volume:          BGM 音量 0.0-1.0，默认 0.5
  - sfx_volume:          音效音量 0.0-1.0，默认 0.7
  - bgm_muted:           BGM 静音开关，默认 False
  - screen_brightness:   屏幕亮度 0.3-1.0，默认 1.0

设置实时生效，返回菜单或退出时自动保存。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.path_utils import get_settings_path


# ── 路径 ─────────────────────────────────────────────────────────
_SETTINGS_FILE: Path = get_settings_path()

# ── 默认值 ───────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict[str, Any] = {
    "bgm_volume": 0.5,
    "sfx_volume": 0.7,
    "bgm_muted": False,
    "screen_brightness": 1.0,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    """将数值限制在 [lo, hi] 范围内。"""
    return max(lo, min(hi, value))


class SettingsManager:
    """设置管理器类，封装加载、保存与状态访问。"""

    def __init__(self):
        self.settings: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        """内部加载逻辑：文件不存在或损坏时返回默认值副本。"""
        if not _SETTINGS_FILE.exists():
            return dict(DEFAULT_SETTINGS)
        try:
            raw_text = _SETTINGS_FILE.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[SettingsManager] 设置文件损坏，使用默认值: {exc}")
            return dict(DEFAULT_SETTINGS)

        if not isinstance(data, dict):
            return dict(DEFAULT_SETTINGS)

        # 补齐缺失字段
        for key, default_val in DEFAULT_SETTINGS.items():
            data.setdefault(key, default_val)

        # 类型修正
        data["bgm_volume"] = _clamp(float(data.get("bgm_volume", 0.5)), 0.0, 1.0)
        data["sfx_volume"] = _clamp(float(data.get("sfx_volume", 0.7)), 0.0, 1.0)
        data["bgm_muted"] = bool(data.get("bgm_muted", False))
        data["screen_brightness"] = _clamp(float(data.get("screen_brightness", 1.0)), 0.3, 1.0)

        return data

    def save(self) -> None:
        """将当前设置持久化到 settings.json。"""
        try:
            _SETTINGS_FILE.write_text(
                json.dumps(self.settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[SettingsManager] 设置写入失败: {exc}")


# ── 兼容旧版函数式调用 ────────────────────────────────────────
def load_settings() -> dict[str, Any]:
    """快捷加载函数。"""
    return SettingsManager().settings


def save_settings(settings: dict[str, Any]) -> None:
    """快捷保存函数。"""
    mgr = SettingsManager()
    mgr.settings = settings
    mgr.save()
