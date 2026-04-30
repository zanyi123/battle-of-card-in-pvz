"""ui/loading_screen.py - PVZ 植物卡牌对战加载界面。

提供：
  - LoadingScreen 类：PVZ 风格滚动进度条 + 背景图
  - update(dt) / draw(screen) 标准接口
  - 模拟资源加载进度（0→100），完成后回调跳转
  - 支持背景图（bg_garden.png）和加载音乐（080 Opening.Splash.mp3）

进度条设计：
  - 底部渐变填充条（深绿→亮绿）
  - 上方中央显示 "Loading..." + 百分比
  - 背景图覆盖全屏
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional

import pygame

from utils.path_utils import get_resource_path


# ── 颜色常量 ─────────────────────────────────────────────────────
_BAR_BG: tuple[int, int, int] = (20, 40, 25)
_BAR_FILL_START: tuple[int, int, int] = (34, 139, 34)   # 深绿
_BAR_FILL_END: tuple[int, int, int] = (124, 252, 0)     # 亮绿
_TEXT_COLOR: tuple[int, int, int] = (220, 235, 200)
_ACCENT_COLOR: tuple[int, int, int] = (255, 220, 80)

# ── 资源路径常量 ─────────────────────────────────────────────────
_IMG_ROOT = get_resource_path("assets/images")
_MUSIC_ROOT = get_resource_path("assets/music/loading_page")
_SFX_ROOT = get_resource_path("assets/sfx")
_LOADING_MUSIC = "080. Opening Splash.mp3"
_SFX_CLICK = "menu_button.wav"


class LoadingScreen:
    """PVZ 风格加载界面。

    用法::

        loading = LoadingScreen(screen, screen_size, on_complete_callback)
        running = True
        while running:
            dt = clock.tick(60) / 1000.0
            done = loading.update(dt)
            loading.draw(screen)
            pygame.display.flip()
            if done:
                # 回调已触发，退出加载循环
                break
    """

    # 进度条尺寸
    BAR_WIDTH: int = 600
    BAR_HEIGHT: int = 28
    BAR_Y_OFFSET: int = 80  # 距底部距离

    # 加载总时长（秒），0→100
    LOAD_DURATION: float = 2.5

    def __init__(
        self,
        screen: pygame.Surface,
        screen_size: tuple[int, int],
        on_complete: Optional[Callable[[], None]] = None,
        draw_bg_callback: Optional[Callable[[pygame.Surface], None]] = None,
    ) -> None:
        """初始化加载界面。

        Args:
            screen:         pygame 屏幕 surface
            screen_size:    (width, height)
            on_complete:    进度达到 100% 时的回调函数
            draw_bg_callback: 背景绘制回调，传入 screen，可在进度条下方绘制背景图
        """
        self.screen = screen
        self.screen_w, self.screen_h = screen_size
        self.on_complete = on_complete
        self._draw_bg_callback = draw_bg_callback

        # 进度状态
        self._progress: float = 0.0        # 0.0 ~ 100.0
        self._elapsed: float = 0.0
        self._done: bool = False
        self._callback_fired: bool = False

        # ── "开始游戏" 确认按钮 ────────────────────────────────────
        self._loading_complete: bool = False  # 进度满但等待点击确认
        self._btn_hover: bool = False
        self._btn_w, self._btn_h = 200, 50
        self._btn_rect = pygame.Rect(
            self.screen_w // 2 - self._btn_w // 2,
            self.screen_h - self.BAR_Y_OFFSET - self.BAR_HEIGHT - 80,
            self._btn_w, self._btn_h,
        )

        # ── SFX 音效预加载 ─────────────────────────────────────────
        self._sfx_click: pygame.mixer.Sound | None = None
        self._load_sfx()

        # 字体缓存
        self._font_cache: dict[int, pygame.font.Font] = {}

        # 进度条区域
        bar_x = self.screen_w // 2 - self.BAR_WIDTH // 2
        bar_y = self.screen_h - self.BAR_Y_OFFSET - self.BAR_HEIGHT
        self._bar_rect = pygame.Rect(bar_x, bar_y, self.BAR_WIDTH, self.BAR_HEIGHT)

        # 辉光动画参数
        self._glow_phase: float = 0.0

        # 加载项文字（模拟加载阶段提示）
        self._load_tips: list[str] = [
            "正在加载植物图鉴...",
            "正在初始化卡牌系统...",
            "正在同步音效引擎...",
            "正在读取战场配置...",
            "正在连接植物军团...",
        ]
        self._current_tip: str = self._load_tips[0]
        self._last_tip_index: int = 0

        # 加载背景图
        self._bg: pygame.Surface | None = self._load_bg()

        # 加载音乐
        self._music_played: bool = False

    def _load_bg(self) -> pygame.Surface | None:
        """加载背景图 bg_garden.png。"""
        bg_path = _IMG_ROOT / "bg_garden.png"
        if bg_path.exists():
            try:
                surf = pygame.image.load(str(bg_path)).convert()
                return surf
            except pygame.error:
                return None
        return None

    def _play_loading_music(self) -> None:
        """播放加载界面音乐。"""
        if self._music_played:
            return
        music_path = _MUSIC_ROOT / _LOADING_MUSIC
        if music_path.exists():
            try:
                pygame.mixer.music.load(str(music_path))
                pygame.mixer.music.play(-1)  # 循环播放
                self._music_played = True
            except pygame.error:
                pass

    def _stop_music(self) -> None:
        """停止加载界面音乐。"""
        if self._music_played:
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass
            self._music_played = False

    def _load_sfx(self) -> None:
        """预加载点击音效。"""
        sfx_path = _SFX_ROOT / _SFX_CLICK
        if sfx_path.exists():
            try:
                self._sfx_click = pygame.mixer.Sound(str(sfx_path))
                self._sfx_click.set_volume(0.7)
            except pygame.error:
                self._sfx_click = None

    def _play_click_sfx(self) -> None:
        """播放点击音效。"""
        if self._sfx_click is not None:
            self._sfx_click.play()

    # ── 公共接口 ─────────────────────────────────────────────────

    def update(self, dt: float) -> bool:
        """更新加载进度。

        Args:
            dt: 帧间隔（秒）

        Returns:
            True 表示点击了"开始游戏"按钮，可切换至下一场景
        """
        if self._done:
            return True

        # 播放加载音乐（首次 update 时）
        self._play_loading_music()

        self._elapsed += dt
        self._glow_phase += dt * 2.5

        # 进度插值：0 → 100，使用 ease-out 曲线
        raw_progress = min(1.0, self._elapsed / self.LOAD_DURATION)
        eased = 1.0 - math.pow(1.0 - raw_progress, 2.5)
        self._progress = eased * 100.0

        # 更新提示文字
        tip_index = int(self._progress / 100.0 * len(self._load_tips))
        tip_index = min(tip_index, len(self._load_tips) - 1)
        if tip_index != self._last_tip_index:
            self._last_tip_index = tip_index
            self._current_tip = self._load_tips[tip_index]

        # 进度满 → 进入"等待点击确认"阶段，不立即跳转
        if self._progress >= 100.0 and not self._loading_complete:
            self._progress = 100.0
            self._loading_complete = True
            self._current_tip = "加载完成！"

        return self._done

    def handle_event(self, event: pygame.event.Event) -> None:
        """处理鼠标事件，用于"开始游戏"按钮点击检测。

        应在主循环中调用此方法处理事件。
        """
        if not self._loading_complete:
            return

        mx, my = event.pos if hasattr(event, "pos") else pygame.mouse.get_pos()

        if event.type == pygame.MOUSEMOTION:
            was_hover = self._btn_hover
            self._btn_hover = self._btn_rect.collidepoint(mx, my)
            # 悬停瞬间触发音效
            if self._btn_hover and not was_hover:
                if self._sfx_click is not None:
                    self._sfx_click.play()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._btn_rect.collidepoint(mx, my):
                self._done = True
                self._stop_music()
                if not self._callback_fired and self.on_complete is not None:
                    self._callback_fired = True
                    self.on_complete()

    def draw(self, surface: Optional[pygame.Surface] = None) -> None:
        """绘制加载界面到 surface。"""
        target = surface if surface is not None else self.screen

        # 背景图
        if self._bg is not None:
            bg_scaled = pygame.transform.smoothscale(self._bg, (self.screen_w, self.screen_h))
            target.blit(bg_scaled, (0, 0))
            # 半透明暗色蒙版，让进度条更清晰
            mask = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
            mask.fill((0, 0, 0, 120))
            target.blit(mask, (0, 0))
        else:
            target.fill((15, 22, 30))

        # 背景图回调（可绘制品牌图、logo 等）
        if self._draw_bg_callback is not None:
            self._draw_bg_callback(target)

        # 顶部标题
        self._draw_title(target)

        # 进度条
        self._draw_progress_bar(target)

        # 加载提示
        self._draw_tip(target)

        # "开始游戏" 按钮（进度满后显示）
        if self._loading_complete:
            self._draw_start_button(target)

        # 底部版本信息
        self._draw_footer(target)

    @property
    def progress(self) -> float:
        """当前进度 0.0 ~ 100.0。"""
        return self._progress

    @property
    def is_done(self) -> bool:
        return self._done

    # ── 内部绘制方法 ─────────────────────────────────────────────

    def _draw_title(self, surface: pygame.Surface) -> None:
        """绘制顶部标题。"""
        title_font = self._get_font(36, bold=True)
        title_surf = title_font.render("PVZ 植物卡牌对战", True, _ACCENT_COLOR)
        title_rect = title_surf.get_rect(centerx=self.screen_w // 2, y=80)
        # 阴影
        shadow = title_font.render("PVZ 植物卡牌对战", True, (0, 0, 0))
        surface.blit(shadow, (title_rect.x + 3, title_rect.y + 3))
        surface.blit(title_surf, title_rect)

        # 副标题
        sub_font = self._get_font(16)
        sub_surf = sub_font.render("正在初始化游戏资源...", True, (160, 180, 150))
        sub_rect = sub_surf.get_rect(centerx=self.screen_w // 2, y=title_rect.bottom + 8)
        surface.blit(sub_surf, sub_rect)

    def _draw_progress_bar(self, surface: pygame.Surface) -> None:
        """绘制 PVZ 风格渐变进度条。"""
        bar_rect = self._bar_rect

        # 外框（深色背景）
        pygame.draw.rect(surface, _BAR_BG, bar_rect, border_radius=6)

        # 填充区域
        fill_width = max(0, int(bar_rect.width * self._progress / 100.0))
        if fill_width > 0:
            fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, fill_width, bar_rect.height)

            # 渐变效果（逐像素渲染）
            for x in range(fill_rect.width):
                ratio = x / fill_rect.width
                r = int(_BAR_FILL_START[0] + (_BAR_FILL_END[0] - _BAR_FILL_START[0]) * ratio)
                g = int(_BAR_FILL_START[1] + (_BAR_FILL_END[1] - _BAR_FILL_START[1]) * ratio)
                b = int(_BAR_FILL_START[2] + (_BAR_FILL_END[2] - _BAR_FILL_START[2]) * ratio)
                pygame.draw.line(surface, (r, g, b), (bar_rect.x + x, bar_rect.y + 4),
                                 (bar_rect.x + x, bar_rect.bottom - 4))

            # 辉光边缘
            glow_x = bar_rect.x + fill_width - 2
            glow_intensity = int(150 + 50 * abs(math.sin(self._glow_phase)))
            pygame.draw.rect(
                surface,
                (glow_intensity, glow_intensity, 50),
                pygame.Rect(glow_x, bar_rect.y + 2, 4, bar_rect.height - 4),
                border_radius=2,
            )

        # 边框
        pygame.draw.rect(surface, (60, 100, 60), bar_rect, width=2, border_radius=6)

        # 百分比文字（居中）
        pct_font = self._get_font(18, bold=True)
        pct_text = f"{int(self._progress)}%"
        pct_color = (255, 255, 255) if self._progress < 45 else (255, 255, 200)
        pct_surf = pct_font.render(pct_text, True, pct_color)
        # 深色描边
        shadow_surf = pct_font.render(pct_text, True, (0, 0, 0))
        pct_rect = pct_surf.get_rect(center=bar_rect.center)
        surface.blit(shadow_surf, (pct_rect.x + 1, pct_rect.y + 1))
        surface.blit(pct_surf, pct_rect)

    def _draw_tip(self, surface: pygame.Surface) -> None:
        """绘制加载阶段提示。"""
        tip_font = self._get_font(14)
        tip_surf = tip_font.render(self._current_tip, True, (150, 170, 140))
        tip_rect = tip_surf.get_rect(
            centerx=self.screen_w // 2,
            y=self._bar_rect.bottom + 14,
        )
        surface.blit(tip_surf, tip_rect)

    def _draw_start_button(self, surface: pygame.Surface) -> None:
        """绘制"开始游戏"按钮（含悬停高亮）。"""
        # 按钮颜色
        if self._btn_hover:
            bg_color = (72, 108, 140)
            bd_color = (180, 200, 220)
            txt_color = (255, 255, 255)
        else:
            bg_color = (45, 58, 75)
            bd_color = (130, 150, 170)
            txt_color = (235, 240, 245)

        # 按钮背景
        btn_rect = self._btn_rect
        pygame.draw.rect(surface, bg_color, btn_rect, border_radius=10)
        pygame.draw.rect(surface, bd_color, btn_rect, width=2, border_radius=10)

        # 按钮文字
        btn_font = self._get_font(22, bold=True)
        btn_text = btn_font.render("点击开始游戏", True, txt_color)
        surface.blit(btn_text, btn_text.get_rect(center=btn_rect.center))

    def _draw_footer(self, surface: pygame.Surface) -> None:
        """绘制底部版本信息。"""
        footer_font = self._get_font(12)
        footer_text = "v0.2 alpha  |  Plants vs. Zombies Card Battle"
        footer_surf = footer_font.render(footer_text, True, (80, 90, 100))
        footer_rect = footer_surf.get_rect(
            centerx=self.screen_w // 2,
            y=self.screen_h - 20,
        )
        surface.blit(footer_surf, footer_rect)

    # ── 字体缓存 ─────────────────────────────────────────────────

    def _get_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (max(8, size), bold)
        if key not in self._font_cache:
            if not pygame.font.get_init():
                pygame.font.init()
            # 优先使用 CJK 字体
            font_path = get_resource_path("assets/fonts/SourceHanSansSC-Regular.otf")
            fallback_path = get_resource_path("assets/fonts/simhei.ttf")
            if font_path.exists():
                try:
                    self._font_cache[key] = pygame.font.Font(str(font_path), size)
                except Exception:
                    self._font_cache[key] = pygame.font.Font(str(fallback_path) if fallback_path.exists() else None, size)
            elif fallback_path.exists():
                self._font_cache[key] = pygame.font.Font(str(fallback_path), size)
            else:
                try:
                    self._font_cache[key] = pygame.font.SysFont("simhei", size)
                except Exception:
                    self._font_cache[key] = pygame.font.Font(None, size)
            self._font_cache[key].set_bold(bold)
        return self._font_cache[key]


def run_loading_screen(
    screen: pygame.Surface,
    screen_size: tuple[int, int],
    on_complete: Optional[Callable[[], None]] = None,
    draw_bg_callback: Optional[Callable[[pygame.Surface], None]] = None,
    fps: int = 60,
) -> None:
    """便捷入口：阻塞运行加载界面动画，完成后调用回调。"""
    clock = pygame.time.Clock()
    loading = LoadingScreen(
        screen=screen,
        screen_size=screen_size,
        on_complete=on_complete,
        draw_bg_callback=draw_bg_callback,
    )

    while not loading.is_done:
        dt = clock.tick(fps) / 1000.0
        loading.update(dt)
        loading.draw()
        pygame.display.flip()

        # 处理退出事件 & 按钮点击
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            loading.handle_event(event)
