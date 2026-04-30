"""core/music_manager.py - PVZ 植物卡牌对战智能音乐管理系统。

功能：
  - 自动扫描 music/pre_worlds/ 和 music/worlds/ 目录
  - 解析文件名提取世界标识（截取序号后、Battle/Pre Game/Game Start 前的字符串）
  - 建立智能配对字典，支持多BGM世界和单曲循环
  - 提供 pick_random_world() / play_pre() / play_game() / stop() 接口

目录结构（assets/music/）:
  pre_worlds/   → 阵前曲（Pre Game / Battle）
  worlds/        → 游戏BGM（Game Start / Battle）
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pygame

from utils.path_utils import get_resource_path


# ── 路径常量 ─────────────────────────────────────────────────────
# 相对于项目根目录的音乐根目录
MUSIC_ROOT: Path = get_resource_path("assets/music")
PRE_WORLDS_DIR: Path = MUSIC_ROOT / "pre_worlds"
WORLDS_DIR: Path = MUSIC_ROOT / "worlds"
MENU_DIR: Path = MUSIC_ROOT / "menu"

# 循环相关
SINGLE_LOOP_DELAY_MS: int = 5000  # 单曲循环延迟（毫秒）


@dataclass
class _WorldMusic:
    """单个世界的音乐数据。"""
    world_key: str                  # 世界标识（如 "Neon Mixtape Tour"）
    pre: Optional[str] = None      # 阵前曲路径（绝对路径或相对路径）
    game: list[str] = field(default_factory=list)  # 游戏BGM路径列表
    current_index: int = 0          # 当前播放索引
    is_looping: bool = False       # 是否正在单曲循环倒计时


class MusicManager:
    """智能音乐管理器。

    负责：
      - 扫描并解析音乐文件
      - 建立世界 ↔ 音乐配对
      - 阵前曲播放 / 游戏BGM循环播放
      - 单曲循环倒计时
      - 支持通过 settings dict 控制 BGM 音量 / 静音

    用法::

        mm = MusicManager()
        mm.scan()  # 扫描音乐文件

        # 随机选择一个世界
        world = mm.pick_random_world()

        # 播放阵前曲
        mm.play_pre(world)

        # 进入游戏后播放BGM
        mm.play_game(world)

        # 主循环中更新
        mm.update(dt)  # 检测音乐结束、倒计时等
    """

    # 文件名中需要移除的关键词（按优先级排序）
    _PRE_KEYWORDS: tuple[str, ...] = ("Pre Game", "Battle", "Game Start")
    # 特殊世界前缀（多首BGM的世界，需要将所有曲目归为同一世界）
    _SPECIAL_WORLDS: tuple[str, ...] = ("Neon Mixtape Tour",)

    def __init__(
        self,
        music_root: Optional[Path] = None,
        on_music_end: Optional[Callable[[], None]] = None,
        settings: Optional[dict[str, Any]] = None,
    ) -> None:
        """初始化音乐管理器。

        Args:
            music_root: 音乐根目录，默认为 assets/music
            on_music_end: 音乐结束回调（用于通知外部如游戏主循环）
            settings: 设置字典（bgm_volume, bgm_muted）
        """
        self._music_root: Path = music_root if music_root else MUSIC_ROOT
        self._pre_dir: Path = self._music_root / "pre_worlds"
        self._worlds_dir: Path = self._music_root / "worlds"

        # 世界音乐数据
        self._worlds: dict[str, _WorldMusic] = {}
        self._world_keys: list[str] = []  # 用于随机选择

        # 当前播放状态
        self._current_world: Optional[str] = None
        self._is_pre_playing: bool = False

        # 单曲循环倒计时
        self._loop_timer_ms: int = 0
        self._loop_start_ms: int = 0

        # 回调
        self._on_music_end: Optional[Callable[[], None]] = on_music_end

        # 是否已初始化 mixer
        self._mixer_init: bool = False

        # 已知的世界名列表（用于日志）
        self._known_worlds: list[str] = []

        # ── 设置集成（BGM 音量 / 静音）────────────────────────────
        self._settings: dict[str, Any] = settings or {}
        self._bgm_muted: bool = bool(self._settings.get("bgm_muted", False))
        self._bgm_volume: float = float(self._settings.get("bgm_volume", 0.5))
        self._sfx_volume: float = float(self._settings.get("sfx_volume", 0.7))

    # ── 公共接口 ─────────────────────────────────────────────────

    def update_settings(self, settings: dict[str, Any]) -> None:
        """从外部设置字典同步音量/静音参数，立即生效。"""
        self._settings = settings
        self._bgm_muted = bool(settings.get("bgm_muted", False))
        self._bgm_volume = float(settings.get("bgm_volume", 0.5))
        self._sfx_volume = float(settings.get("sfx_volume", 0.7))
        self._apply_volume()

    def _apply_volume(self) -> None:
        """立即将当前设置应用到 pygame.mixer.music。"""
        if not self._mixer_init:
            return
        if self._bgm_muted:
            pygame.mixer.music.set_volume(0)
        else:
            pygame.mixer.music.set_volume(self._bgm_volume)

    @property
    def sfx_volume(self) -> float:
        """返回当前音效音量（供 SFX 播放器读取）。"""
        return self._sfx_volume

    def scan(self) -> None:
        """扫描音乐目录，建立世界 ↔ 音乐配对。

        同名音乐处理：以首次扫描到的世界名为准进行绑定。
        """
        self._worlds.clear()
        self._world_keys.clear()
        self._known_worlds.clear()

        # 已绑定到某世界的音乐文件（用于去重）
        bound_files: set[str] = set()

        # 先扫描 pre_worlds，建立世界基础
        self._scan_pre_worlds(bound_files)

        # 再扫描 worlds，补充游戏BGM
        self._scan_worlds(bound_files)

        # 更新世界键列表
        self._world_keys = list(self._worlds.keys())
        self._known_worlds = self._world_keys.copy()

        # 打印配对验证日志
        self._log_pairing()

    def _scan_pre_worlds(self, bound_files: set[str]) -> None:
        """扫描阵前曲目录。"""
        if not self._pre_dir.exists():
            return

        for entry in sorted(self._pre_dir.iterdir()):
            if entry.suffix.lower() not in (".mp3", ".wav", ".ogg"):
                continue

            world_key = self._parse_filename(entry.name)
            if not world_key:
                continue

            file_str = str(entry.resolve())
            if file_str in bound_files:
                continue
            bound_files.add(file_str)

            if world_key not in self._worlds:
                self._worlds[world_key] = _WorldMusic(world_key=world_key)
            self._worlds[world_key].pre = file_str

    def _scan_worlds(self, bound_files: set[str]) -> None:
        """扫描游戏BGM目录。"""
        if not self._worlds_dir.exists():
            return

        for entry in sorted(self._worlds_dir.iterdir()):
            if entry.suffix.lower() not in (".mp3", ".wav", ".ogg"):
                continue

            world_key = self._parse_filename(entry.name)
            if not world_key:
                continue

            file_str = str(entry.resolve())
            if file_str in bound_files:
                # 同一文件已在pre_worlds中绑定，跳过
                continue
            bound_files.add(file_str)

            if world_key not in self._worlds:
                self._worlds[world_key] = _WorldMusic(world_key=world_key)
            self._worlds[world_key].game.append(file_str)

    def _parse_filename(self, filename: str) -> Optional[str]:
        """从文件名解析世界名称。

        支持格式：
          - "005. Ancient Egypt Pre Game.mp3" → "Ancient Egypt"
          - "076. Neon Mixtape Tour – Sincerely the Theme.mp3" → "Neon Mixtape Tour"
          - "053. Kong Fu World Battle.mp3" → "Kong Fu World"
          - "100. Sky City Battle.mp3" → "Sky City"

        Returns:
            世界名称，解析失败返回 None
        """
        # 移除扩展名
        base = filename.rsplit(".", 1)[0]

        # 首先检查是否是特殊世界（多首BGM的世界）
        for special_world in self._SPECIAL_WORLDS:
            if special_world in base:
                # 移除曲目名后缀（如 " – Sincerely the Theme"）
                for kw in self._PRE_KEYWORDS:
                    if kw in base:
                        return special_world
                # 如果没有关键词，也返回特殊世界名
                return special_world

        # 标准解析：移除关键词
        raw = base
        for kw in self._PRE_KEYWORDS:
            if kw in raw:
                raw = raw.split(kw)[0].strip()
                break

        # 移除序号前缀 "005. " 或 "76. "
        # 正则：匹配 "数字. " 后面的内容
        match = re.match(r"^\d+\.\s*(.+)$", raw)
        if match:
            world_name = match.group(1).strip()
            if world_name:
                # 移除可能残留的连字符和空格
                world_name = world_name.rstrip(" -")
                return world_name if world_name else None

        return None

    def _log_pairing(self) -> None:
        """打印配对验证日志。"""
        print(f"[*Music*] 已扫描 {len(self._worlds)} 个世界")

        for world_key, wm in sorted(self._worlds.items()):
            pre_id = self._extract_id(wm.pre) if wm.pre else "无"
            game_ids = [self._extract_id(p) for p in wm.game]
            game_count = len(wm.game)

            if game_count == 1:
                loop_info = "（单曲循环）"
            elif game_count > 1:
                loop_info = f"（{game_count}首循环）"
            else:
                loop_info = ""

            print(
                f"[*Music*] 匹配世界: {world_key} | "
                f"阵前曲: {pre_id} | "
                f"游戏曲: {game_ids} ({game_count}首){loop_info}"
            )

    def _extract_id(self, filepath: Optional[str]) -> str:
        """从路径中提取序号（如 "005", "076"）。"""
        if not filepath:
            return "?"
        # 匹配路径中最后一个 / 或 \ 后面的数字
        match = re.search(r"[\\/](\d+)\.", filepath)
        return match.group(1) if match else "?"

    def init_mixer(self) -> None:
        """初始化 pygame.mixer（延迟初始化）。"""
        if not self._mixer_init:
            try:
                pygame.mixer.init()
                self._mixer_init = True
            except pygame.error as exc:
                print(f"[*Music*] Mixer 初始化失败: {exc}")

    def quit_mixer(self) -> None:
        """安全释放 mixer。"""
        if self._mixer_init:
            pygame.mixer.quit()
            self._mixer_init = False

    def pick_random_world(self) -> str:
        """随机选择一个世界。

        Returns:
            世界名称字符串

        Raises:
            RuntimeError: 如果尚未调用 scan()
        """
        if not self._world_keys:
            raise RuntimeError("[*Music*] 必须先调用 scan()")
        return random.choice(self._world_keys)

    def play_pre(self, world_key: str) -> bool:
        """播放指定世界的阵前曲（不循环）。

        Args:
            world_key: 世界名称

        Returns:
            是否成功播放
        """
        if world_key not in self._worlds:
            print(f"[*Music*] 未找到世界: {world_key}")
            return False

        wm = self._worlds[world_key]
        if not wm.pre:
            print(f"[*Music*] 世界 {world_key} 无阵前曲")
            return False

        self._stop_current()
        self._is_pre_playing = True
        self._current_world = world_key

        try:
            pygame.mixer.music.load(wm.pre)
            if self._bgm_muted:
                pygame.mixer.music.set_volume(0)
            else:
                pygame.mixer.music.set_volume(self._bgm_volume)
            pygame.mixer.music.play()
            print(f"[*Music*] 播放阵前曲: {world_key}")
            return True
        except pygame.error as exc:
            print(f"[*Music*] 播放失败 ({wm.pre}): {exc}")
            return False

    def play_game(self, world_key: str) -> bool:
        """播放指定世界的游戏BGM列表。

        - 若只有1首：单曲循环（5秒倒计时后重播）
        - 若有多首：按顺序播放，播完从头循环

        Args:
            world_key: 世界名称

        Returns:
            是否成功开始播放
        """
        if world_key not in self._worlds:
            print(f"[*Music*] 未找到世界: {world_key}")
            return False

        wm = self._worlds[world_key]
        if not wm.game:
            print(f"[*Music*] 世界 {world_key} 无游戏BGM")
            return False

        self._stop_current()
        self._is_pre_playing = False
        self._current_world = world_key
        wm.current_index = 0
        wm.is_looping = False
        self._loop_timer_ms = 0

        return self._play_current_track(world_key)

    def _play_current_track(self, world_key: str) -> bool:
        """播放当前世界的当前曲目。"""
        if world_key not in self._worlds:
            return False

        wm = self._worlds[world_key]
        if wm.current_index >= len(wm.game):
            wm.current_index = 0

        track_path = wm.game[wm.current_index]
        try:
            pygame.mixer.music.load(track_path)
            if self._bgm_muted:
                pygame.mixer.music.set_volume(0)
            else:
                pygame.mixer.music.set_volume(self._bgm_volume)
            pygame.mixer.music.play()
            print(
                f"[*Music*] 播放游戏BGM: {world_key} "
                f"[{wm.current_index + 1}/{len(wm.game)}]"
            )
            return True
        except pygame.error as exc:
            print(f"[*Music*] 播放失败 ({track_path}): {exc}")
            return False

    def update(self, dt: float) -> None:
        """更新音乐状态：检测音乐结束、处理单曲循环倒计时。

        应在游戏主循环中每帧调用。

        Args:
            dt: 帧间隔（秒）
        """
        if not self._mixer_init or self._current_world is None:
            return

        # 检测阵前曲结束
        if self._is_pre_playing:
            if not pygame.mixer.music.get_busy():
                self._is_pre_playing = False
                if self._on_music_end:
                    self._on_music_end()

        # 处理单曲循环倒计时
        else:
            self._update_single_loop(dt)

    def _update_single_loop(self, dt: float) -> None:
        """更新单曲循环倒计时。"""
        if self._current_world is None:
            return

        wm = self._worlds.get(self._current_world)
        if wm is None or len(wm.game) != 1:
            # 非单曲模式，依赖 pygame.mixer 事件检测
            if wm is not None and not pygame.mixer.music.get_busy():
                # 音乐结束，播放下一首（如果有）
                if len(wm.game) > 1:
                    wm.current_index = (wm.current_index + 1) % len(wm.game)
                    self._play_current_track(self._current_world)
            return

        # 单曲模式
        if pygame.mixer.music.get_busy():
            self._loop_timer_ms = 0
            return

        # 音乐停止，增加倒计时
        if self._loop_timer_ms == 0:
            self._loop_start_ms = pygame.time.get_ticks()
            print(f"[*Loop*] {wm.world_key} 5秒后重播...")

        self._loop_timer_ms += int(dt * 1000)

        if self._loop_timer_ms >= SINGLE_LOOP_DELAY_MS:
            self._loop_timer_ms = 0
            self._play_current_track(self._current_world)

    def stop(self) -> None:
        """停止播放并清除倒计时。"""
        self._stop_current()
        self._current_world = None
        self._loop_timer_ms = 0

    def _stop_current(self) -> None:
        """停止当前播放。"""
        if self._mixer_init:
            pygame.mixer.music.stop()
        self._is_pre_playing = False
        self._loop_timer_ms = 0

    @property
    def worlds(self) -> list[str]:
        """返回所有已扫描的世界名称列表。"""
        return self._known_worlds.copy()

    @property
    def current_world(self) -> Optional[str]:
        """返回当前播放的世界名称。"""
        return self._current_world

    @property
    def is_playing(self) -> bool:
        """返回是否正在播放。"""
        return self._mixer_init and pygame.mixer.music.get_busy()
