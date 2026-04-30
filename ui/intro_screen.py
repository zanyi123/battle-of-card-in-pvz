"""ui/intro_screen.py - PVZ 植物卡牌对战致谢入场动画。

启动流程：INTRO → LOADING → MENU → GAME

动画阶段：
  - Phase 0 (黑屏)  : 2 秒纯黑
  - Phase 1 (淡入)  : 2 秒 Alpha 0→255 线性插值
  - Phase 2 (停留)  : 2 秒保持完全不透明
  - Phase 3 (完成)  : 返回 True，切换至 LoadingScreen

布局：2 行 × 3 列 矩阵，整体居中
  第一行：PVZ2 Official | zanyi | qwen
  第二行：work buddy    | cursor | 即梦 AI

图片路径：assets/images/auth_pic/
  pvz2_pic.png / zanyi_pic.jpg / qwen_pic.png /
  buddy_pic.png / cursor_pic.png / jimeng_pic.png

容错：图片缺失 → 深灰圆角矩形 + 首字母占位符（不崩溃）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame

from utils.path_utils import get_resource_path


# ── 颜色常量 ─────────────────────────────────────────────────────
_BLACK:             tuple[int, int, int] = (0, 0, 0)
_WHITE:             tuple[int, int, int] = (255, 255, 255)
_GRAY_PLACEHOLDER:  tuple[int, int, int] = (50, 50, 55)
_GRAY_BORDER:       tuple[int, int, int] = (80, 80, 88)

# ── 资源根目录 ───────────────────────────────────────────────────
_IMG_ROOT   = get_resource_path("assets/images/auth_pic")
_MUSIC_ROOT = get_resource_path("assets/music/loading_page")
_LOADING_MUSIC = "080. Opening Splash.mp3"

# ── 阶段时长（秒） ───────────────────────────────────────────────
_PHASE_DURATIONS: tuple[float, float, float] = (2.0, 2.0, 2.0)

# ── 布局参数 ─────────────────────────────────────────────────────
_AVATAR_SIZE:    int = 90    # 头像显示边长（像素）
_COL_GAP:        int = 60    # 列间距（图标右边缘 → 下一图标左边缘）
_ROW_GAP:        int = 60    # 行间距（图标底边 → 下一行图标顶边）
_NAME_MARGIN:    int = 8     # 文字距头像底部像素
_NAME_FONT_SIZE: int = 22    # 称号文字字号
_SAFE_MARGIN:    int = 100   # 距屏幕边缘最小安全边距（像素）

# ── 鸣谢矩阵定义（行优先顺序）────────────────────────────────────
# 每项：(显示名, 图片文件名)
_GRID: list[list[tuple[str, str]]] = [
    [
        ("PVZ2 Official", "pvz2_pic.png"),
        ("zanyi",         "zanyi_pic.jpg"),
        ("qwen",          "qwen_pic.png"),
    ],
    [
        ("work buddy",    "buddy_pic.png"),
        ("cursor",        "cursor_pic.png"),
        ("即梦 AI",        "jimeng_pic.png"),
    ],
]

_ROWS:  int = 2
_COLS:  int = 3


class _Cell:
    """矩阵中单个鸣谢项。"""

    __slots__ = ("display_name", "image_file", "avatar", "first_letter")

    def __init__(self, display_name: str, image_file: str) -> None:
        self.display_name: str = display_name
        self.image_file:   str = image_file
        self.avatar:       Optional[pygame.Surface] = None
        self.first_letter: str = display_name[0] if display_name else "?"


class IntroScreen:
    """致谢入场动画（2×3 网格布局，黑屏淡入停留）。

    用法::

        intro = IntroScreen(screen)
        clock = pygame.time.Clock()
        while not intro.is_done:
            dt = clock.tick(60) / 1000.0
            intro.update(dt)
            intro.draw()
            pygame.display.flip()
    """

    def __init__(self, screen: pygame.Surface) -> None:
        """初始化致谢动画。

        Args:
            screen: pygame 屏幕 Surface
        """
        self.screen   = screen
        self.screen_w: int = screen.get_width()
        self.screen_h: int = screen.get_height()

        # ── 字体缓存 ──────────────────────────────────────────────
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}

        # ── 阶段状态 ──────────────────────────────────────────────
        self._phase:         int   = 0      # 0=黑屏 1=淡入 2=停留 3=完成
        self._phase_elapsed: float = 0.0
        self._alpha:         float = 0.0    # 0..255
        self._done:          bool  = False

        # ── 游戏启动时立即播放加载音乐 ─────────────────────────────
        self._play_intro_music()

        # ── 构建网格数据并预加载头像 ──────────────────────────────
        self._cells: list[list[_Cell]] = self._build_cells()

        # ── 计算布局坐标 ──────────────────────────────────────────
        self._start_x: int
        self._start_y: int
        self._cell_step_x: int   # 每列步进（头像宽 + 列间距）
        self._cell_step_y: int   # 每行步进（头像高 + 文字区 + 行间距）
        self._name_h: int        # 称号文字行高（动态量测）
        self._compute_layout()

        # ── 内容 Surface（整体 alpha 混合用） ─────────────────────
        self._content_surf: pygame.Surface = pygame.Surface(
            (self.screen_w, self.screen_h), pygame.SRCALPHA
        )

    def _play_intro_music(self) -> None:
        """游戏启动时立即播放 080 Opening Splash.mp3（循环）。"""
        music_path = _MUSIC_ROOT / _LOADING_MUSIC
        if music_path.exists():
            try:
                pygame.mixer.music.load(str(music_path))
                pygame.mixer.music.play(-1)   # -1 = 无限循环
            except pygame.error:
                pass

    # ── 构建网格 ─────────────────────────────────────────────────

    def _build_cells(self) -> list[list[_Cell]]:
        """构建 2×3 Cell 矩阵并预加载头像图片。"""
        grid: list[list[_Cell]] = []
        for row_def in _GRID:
            row_cells: list[_Cell] = []
            for display_name, img_file in row_def:
                cell = _Cell(display_name, img_file)
                img_path = _IMG_ROOT / img_file
                if img_path.exists():
                    try:
                        raw = pygame.image.load(str(img_path)).convert_alpha()
                        cell.avatar = pygame.transform.smoothscale(
                            raw, (_AVATAR_SIZE, _AVATAR_SIZE)
                        )
                    except pygame.error:
                        cell.avatar = None
                row_cells.append(cell)
            grid.append(row_cells)
        return grid

    # ── 布局计算 ─────────────────────────────────────────────────

    def _compute_layout(self) -> None:
        """动态计算矩阵起始坐标及步进量，保证内容整体居中并满足安全边距。"""
        name_font = self._get_font(_NAME_FONT_SIZE, bold=True)
        self._name_h = name_font.get_height()

        # 单元格宽：头像 + 列间距
        self._cell_step_x = _AVATAR_SIZE + _COL_GAP

        # 单元格高：头像 + 名称边距 + 文字高 + 行间距
        cell_content_h = _AVATAR_SIZE + _NAME_MARGIN + self._name_h
        self._cell_step_y = cell_content_h + _ROW_GAP

        # 整体内容尺寸
        # 宽：3个头像 + 2个列间距
        total_w = _COLS * _AVATAR_SIZE + (_COLS - 1) * _COL_GAP
        # 高：2行内容 + 1个行间距（行间距在两行内容之间，即第1行内容底 到 第2行内容顶）
        total_h = _ROWS * cell_content_h + (_ROWS - 1) * _ROW_GAP

        # 起始坐标（整体居中）
        raw_x = (self.screen_w - total_w) // 2
        raw_y = (self.screen_h - total_h) // 2

        # 安全边距夹紧
        self._start_x = max(_SAFE_MARGIN, raw_x)
        self._start_y = max(_SAFE_MARGIN, raw_y)

    # ── 公共接口 ─────────────────────────────────────────────────

    def update(self, dt: float) -> bool:
        """更新动画阶段。

        Args:
            dt: 帧间隔（秒）

        Returns:
            True 表示动画播放完毕，可切换至下一场景
        """
        if self._done:
            return True

        self._phase_elapsed += dt

        if self._phase == 0:
            # 黑屏
            self._alpha = 0.0
            if self._phase_elapsed >= _PHASE_DURATIONS[0]:
                self._phase = 1
                self._phase_elapsed = 0.0

        elif self._phase == 1:
            # 线性淡入
            ratio = min(1.0, self._phase_elapsed / _PHASE_DURATIONS[1])
            self._alpha = ratio * 255.0
            if self._phase_elapsed >= _PHASE_DURATIONS[1]:
                self._alpha = 255.0
                self._phase = 2
                self._phase_elapsed = 0.0

        elif self._phase == 2:
            # 停留
            self._alpha = 255.0
            if self._phase_elapsed >= _PHASE_DURATIONS[2]:
                self._phase = 3
                self._done = True

        return self._done

    def draw(self) -> None:
        """绘制当前帧到 self.screen。"""
        self.screen.fill(_BLACK)

        if self._phase == 0 or self._alpha <= 0:
            return

        # 将内容画到临时 Surface，再整体 alpha 叠加
        self._content_surf.fill((0, 0, 0, 0))
        self._render_grid(self._content_surf)
        self._content_surf.set_alpha(max(0, min(255, int(self._alpha))))
        self.screen.blit(self._content_surf, (0, 0))

    @property
    def is_done(self) -> bool:
        """动画是否播放完毕。"""
        return self._done

    # ── 渲染 ─────────────────────────────────────────────────────

    def _render_grid(self, surface: pygame.Surface) -> None:
        """将 2×3 鸣谢网格渲染到给定 Surface。"""
        name_font = self._get_font(_NAME_FONT_SIZE, bold=True)

        for row_idx, row_cells in enumerate(self._cells):
            for col_idx, cell in enumerate(row_cells):
                # ── 计算当前格子左上角坐标 ────────────────────────
                ax = self._start_x + col_idx * self._cell_step_x
                ay = self._start_y + row_idx * self._cell_step_y

                # ── 头像 ──────────────────────────────────────────
                if cell.avatar is not None:
                    surface.blit(cell.avatar, (ax, ay))
                else:
                    self._draw_placeholder(surface, ax, ay, cell.first_letter)

                # ── 称号文字（加粗白色，头像正下方居中） ──────────
                name_surf = name_font.render(cell.display_name, True, _WHITE)
                name_rect = name_surf.get_rect(
                    centerx=ax + _AVATAR_SIZE // 2,
                    y=ay + _AVATAR_SIZE + _NAME_MARGIN,
                )
                surface.blit(name_surf, name_rect)

    def _draw_placeholder(
        self,
        surface: pygame.Surface,
        x: int,
        y: int,
        letter: str,
    ) -> None:
        """图片缺失时渲染深灰圆角矩形 + 首字母占位符。"""
        rect = pygame.Rect(x, y, _AVATAR_SIZE, _AVATAR_SIZE)
        pygame.draw.rect(surface, _GRAY_PLACEHOLDER, rect, border_radius=14)
        pygame.draw.rect(surface, _GRAY_BORDER, rect, width=2, border_radius=14)
        ltr_font = self._get_font(32, bold=True)
        ltr_surf = ltr_font.render(letter.upper(), True, (170, 170, 180))
        surface.blit(ltr_surf, ltr_surf.get_rect(center=rect.center))

    # ── 字体缓存 ─────────────────────────────────────────────────

    def _get_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        """获取字体（优先项目 CJK 字体，回退内置字体）。"""
        key = (max(8, size), bold)
        if key not in self._font_cache:
            if not pygame.font.get_init():
                pygame.font.init()
            font_path = get_resource_path("assets/fonts/SourceHanSansSC-Regular.otf")
            fallback_path = get_resource_path("assets/fonts/simhei.ttf")
            if font_path.exists():
                try:
                    f = pygame.font.Font(str(font_path), size)
                except Exception:
                    f = pygame.font.Font(str(fallback_path) if fallback_path.exists() else None, size)
            elif fallback_path.exists():
                f = pygame.font.Font(str(fallback_path), size)
            else:
                try:
                    f = pygame.font.SysFont("microsoftyahei", size)
                except Exception:
                    f = pygame.font.Font(None, size)
            f.set_bold(bold)
            self._font_cache[key] = f
        return self._font_cache[key]
