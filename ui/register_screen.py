"""ui/register_screen.py - 首次启动玩家注册界面。

界面元素：
  - 标题 "欢迎来到 PVZ 植物卡牌对战"
  - 副标题 "请输入你的玩家名字"
  - 文本输入框（白色背景，黑色文字）
  - "确认" 按钮
  - 底部提示 "你的 ID 将自动生成"
"""
from __future__ import annotations

import pygame
from pathlib import Path
from typing import Optional

from core.player_profile import create_profile, is_registered


# ── 颜色 ─────────────────────────────────────────────────────
_BG_COLOR      = (26, 43, 58)
_INPUT_BG      = (245, 245, 250)
_INPUT_BORDER  = (130, 150, 170)
_INPUT_ACTIVE  = (72, 108, 200)
_TITLE_COLOR   = (255, 240, 140)
_SUBTITLE_CLR  = (190, 210, 230)
_HINT_COLOR    = (120, 130, 145)
_BTN_NORMAL    = (45, 58, 75)
_BTN_HOVER     = (72, 108, 140)
_BTN_ACTIVE    = (55, 140, 90)
_BTN_BORDER    = (130, 150, 170)
_BTN_TXT       = (235, 240, 245)


class RegisterScreen:
    """玩家首次注册界面。"""

    def __init__(self, screen: pygame.Surface, screen_size: tuple[int, int]) -> None:
        self.screen = screen
        self.sw, self.sh = screen_size
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self._cjk_font_path = Path("assets/fonts/SourceHanSansSC-Regular.otf")

        # 输入框状态
        self._input_text: str = ""
        self._input_active: bool = True
        self._cursor_visible: bool = True
        self._cursor_timer: float = 0.0

        # 输入框 Rect（居中）
        iw, ih = 320, 44
        self._input_rect = pygame.Rect(
            (self.sw - iw) // 2, self.sh // 2 - 10, iw, ih
        )

        # 确认按钮 Rect
        bw, bh = 140, 42
        self._btn_rect = pygame.Rect(
            (self.sw - bw) // 2, self._input_rect.bottom + 30, bw, bh
        )
        self._btn_hover: bool = False

        # 注册完成标志
        self._done: bool = False
        self._error_msg: str = ""

    @property
    def done(self) -> bool:
        return self._done

    def get_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        if not pygame.font.get_init():
            pygame.font.init()
        key = (max(8, int(size)), bool(bold))
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        if self._cjk_font_path.exists():
            font = pygame.font.Font(str(self._cjk_font_path), key[0])
        else:
            font = pygame.font.SysFont("simhei", key[0])
        font.set_bold(key[1])
        self._font_cache[key] = font
        return font

    def handle_event(self, event: pygame.event.Event) -> None:
        """处理事件。"""
        if self._done:
            return

        if event.type == pygame.MOUSEMOTION:
            self._btn_hover = self._btn_rect.collidepoint(event.pos)
            self._input_active = self._input_rect.collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._btn_rect.collidepoint(event.pos):
                self._try_register()
            self._input_active = self._input_rect.collidepoint(event.pos)

        elif event.type == pygame.KEYDOWN:
            if not self._input_active:
                return
            if event.key == pygame.K_RETURN:
                self._try_register()
            elif event.key == pygame.K_BACKSPACE:
                self._input_text = self._input_text[:-1]
                self._error_msg = ""
            elif event.key == pygame.K_TAB:
                pass  # 忽略 Tab
            else:
                # 限制名字长度 12 字符
                if len(self._input_text) < 12 and event.unicode.isprintable() and event.unicode:
                    self._input_text += event.unicode
                    self._error_msg = ""

    def update(self, dt: float) -> None:
        """更新光标闪烁。"""
        self._cursor_timer += dt
        if self._cursor_timer >= 0.5:
            self._cursor_timer = 0.0
            self._cursor_visible = not self._cursor_visible

    def _try_register(self) -> None:
        """尝试注册。"""
        name = self._input_text.strip()
        if not name:
            self._error_msg = "名字不能为空！"
            return
        if len(name) < 1:
            self._error_msg = "名字至少 1 个字符"
            return

        create_profile(name)
        self._done = True

    def draw(self) -> None:
        """绘制注册界面。"""
        self.screen.fill(_BG_COLOR)

        # ── 标题 ───────────────────────────────────────────────
        title_font = self.get_font(32, bold=True)
        title_surf = title_font.render("欢迎来到 PVZ 植物卡牌对战", True, _TITLE_COLOR)
        self.screen.blit(
            title_surf,
            title_surf.get_rect(centerx=self.sw // 2, y=self.sh // 2 - 120),
        )

        # ── 副标题 ─────────────────────────────────────────────
        sub_font = self.get_font(18)
        sub_surf = sub_font.render("请输入你的玩家名字", True, _SUBTITLE_CLR)
        self.screen.blit(
            sub_surf,
            sub_surf.get_rect(centerx=self.sw // 2, y=self.sh // 2 - 65),
        )

        # ── 输入框 ─────────────────────────────────────────────
        border_color = _INPUT_ACTIVE if self._input_active else _INPUT_BORDER
        # 外框（2px 边框效果）
        outer = self._input_rect.inflate(4, 4)
        pygame.draw.rect(self.screen, border_color, outer, border_radius=8)
        # 内部白色背景
        pygame.draw.rect(self.screen, _INPUT_BG, self._input_rect, border_radius=6)

        # 文本
        input_font = self.get_font(20)
        txt_surf = input_font.render(self._input_text, True, (30, 30, 30))
        txt_x = self._input_rect.x + 12
        txt_y = self._input_rect.centery - txt_surf.get_height() // 2
        # 裁剪区域
        clip = self.screen.get_clip()
        self.screen.set_clip(self._input_rect)
        self.screen.blit(txt_surf, (txt_x, txt_y))
        # 光标
        if self._input_active and self._cursor_visible:
            cursor_x = txt_x + txt_surf.get_width() + 2
            pygame.draw.line(
                self.screen, (30, 30, 30),
                (cursor_x, self._input_rect.y + 8),
                (cursor_x, self._input_rect.bottom - 8),
                2,
            )
        self.screen.set_clip(clip)

        # ── 错误提示 ───────────────────────────────────────────
        if self._error_msg:
            err_font = self.get_font(14)
            err_surf = err_font.render(self._error_msg, True, (220, 60, 60))
            self.screen.blit(
                err_surf,
                err_surf.get_rect(centerx=self.sw // 2, y=self._input_rect.bottom + 6),
            )

        # ── 确认按钮 ───────────────────────────────────────────
        btn_color = _BTN_HOVER if self._btn_hover else _BTN_ACTIVE
        pygame.draw.rect(self.screen, btn_color, self._btn_rect, border_radius=8)
        pygame.draw.rect(self.screen, _BTN_BORDER, self._btn_rect, width=2, border_radius=8)
        btn_font = self.get_font(18, bold=True)
        btn_surf = btn_font.render("确认注册", True, _BTN_TXT)
        self.screen.blit(btn_surf, btn_surf.get_rect(center=self._btn_rect.center))

        # ── 底部提示 ───────────────────────────────────────────
        hint_font = self.get_font(13)
        hint_surf = hint_font.render("你的唯一 ID 将在注册后自动生成（UUID4）", True, _HINT_COLOR)
        self.screen.blit(
            hint_surf,
            hint_surf.get_rect(centerx=self.sw // 2, y=self._btn_rect.bottom + 20),
        )


def ensure_registered(screen: pygame.Surface, screen_size: tuple[int, int]) -> bool:
    """确保玩家已注册，未注册则弹出注册界面。

    Args:
        screen: pygame 屏幕
        screen_size: (width, height)

    Returns:
        True 已注册，False 用户关闭窗口
    """
    if is_registered():
        return True

    reg = RegisterScreen(screen, screen_size)
    clock = pygame.time.Clock()

    while not reg.done:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            reg.handle_event(event)

        reg.update(dt)
        reg.draw()
        pygame.display.flip()

    return True
