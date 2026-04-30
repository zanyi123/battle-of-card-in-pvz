"""ui/order_dialog.py - PVZ 先手/后手选择对话框。

在人机对战中，进入游戏前让玩家选择先手出牌还是后手出牌。
只决定当前这一场比赛的出牌顺序。

提供：
  - OrderDialog 类：居中模态弹窗
  - 先手 / 后手 两个选择按钮
  - show() / hide() / handle_event() / draw() 标准接口
  - 选择时返回 "P1"（先手）或 "P2"（后手）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame

from utils.path_utils import get_resource_path


# ── 颜色常量 ─────────────────────────────────────────────────────
_DIALOG_BG: tuple[int, int, int] = (50, 50, 80)       # 深蓝灰底
_DIALOG_BG_LIGHT: tuple[int, int, int] = (70, 70, 110) # 浅蓝灰高亮
_DIALOG_BORDER: tuple[int, int, int] = (200, 200, 220)  # 银白边框
_TEXT_COLOR: tuple[int, int, int] = (255, 255, 255)     # 白字
_SHADOW_COLOR: tuple[int, int, int] = (0, 0, 0)         # 阴影
_GOLD_COLOR: tuple[int, int, int] = (255, 215, 0)       # 金色

# 按钮颜色
_BTN_FIRST: tuple[int, int, int] = (39, 174, 96)       # 绿色先手
_BTN_SECOND: tuple[int, int, int] = (41, 128, 185)     # 蓝色后手
_BTN_HOVER_OFFSET: int = 10


class OrderDialog:
    """先手/后手选择对话框。

    居中深色模态弹窗，让玩家选择先手或后手出牌。

    用法::

        dialog = OrderDialog(screen, screen_size)
        dialog.show()
        while dialog.visible:
            dialog.draw(screen)
            pygame.display.flip()
            for event in pygame.event.get():
                dialog.handle_event(event)
        first_player = dialog.result  # "P1" or "P2" or None(取消)
    """

    def __init__(
        self,
        screen: pygame.Surface,
        screen_size: tuple[int, int],
    ) -> None:
        self.screen = screen
        self.screen_w, self.screen_h = screen_size

        # 弹窗尺寸
        dlg_w, dlg_h = 440, 300
        self._dlg_rect = pygame.Rect(
            (screen_size[0] - dlg_w) // 2,
            (screen_size[1] - dlg_h) // 2,
            dlg_w, dlg_h,
        )

        # 按钮尺寸
        btn_w, btn_h = 150, 50
        btn_spacing = 40
        total_btn_w = 2 * btn_w + btn_spacing
        btn_start_x = self._dlg_rect.centerx - total_btn_w // 2
        btn_y = self._dlg_rect.bottom - btn_h - 30

        self._first_btn = pygame.Rect(btn_start_x, btn_y, btn_w, btn_h)
        self._second_btn = pygame.Rect(
            btn_start_x + btn_w + btn_spacing, btn_y, btn_w, btn_h
        )

        # 状态
        self.visible: bool = False
        self.result: Optional[str] = None  # "P1"(先手) / "P2"(后手) / None(取消)

        # 悬停状态
        self._first_hover: bool = False
        self._second_hover: bool = False

        # 动画状态
        self._anim_progress: float = 0.0
        self._animating: bool = False

        # 字体缓存
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}

    # ── 公共接口 ─────────────────────────────────────────────────

    def show(self) -> None:
        """显示对话框。"""
        self.visible = True
        self.result = None
        self._first_hover = False
        self._second_hover = False
        self._anim_progress = 0.0
        self._animating = True

    def hide(self) -> None:
        """隐藏对话框。"""
        self.visible = False
        self._animating = False

    def handle_event(self, event: pygame.event.Event) -> None:
        """处理 pygame 事件。"""
        if not self.visible:
            return

        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self._first_hover = self._first_btn.collidepoint(mx, my)
            self._second_hover = self._second_btn.collidepoint(mx, my)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if self._first_btn.collidepoint(mx, my):
                self.result = "P1"
                self.hide()
            elif self._second_btn.collidepoint(mx, my):
                self.result = "P2"
                self.hide()

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_1):
                self.result = "P1"
                self.hide()
            elif event.key in (pygame.K_2,):
                self.result = "P2"
                self.hide()
            elif event.key in (pygame.K_ESCAPE,):
                self.result = None
                self.hide()

    def update(self, dt: float) -> None:
        """更新动画。"""
        if self._animating:
            self._anim_progress = min(1.0, self._anim_progress + dt * 6.0)
            if self._anim_progress >= 1.0:
                self._animating = False

    def draw(self, surface: Optional[pygame.Surface] = None) -> None:
        """绘制选择对话框。"""
        if not self.visible:
            return

        target = surface if surface is not None else self.screen

        # 半透明遮罩
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        target.blit(overlay, (0, 0))

        # 弹出动画插值
        if self._animating:
            t = self._anim_progress
            scale = 0.5 + 0.5 * t + 0.1 * (1.0 - t) * (1.0 - (1.0 - t) ** 2)
            scale = max(0.1, min(1.0, scale))
        else:
            scale = 1.0

        w, h = self._dlg_rect.width, self._dlg_rect.height
        scaled_w, scaled_h = int(w * scale), int(h * scale)
        anim_rect = pygame.Rect(
            self._dlg_rect.centerx - scaled_w // 2,
            self._dlg_rect.centery - scaled_h // 2,
            scaled_w, scaled_h,
        )

        # 绘制主对话框
        self._draw_dialog_box(target, anim_rect)
        # 绘制内容
        self._draw_content(target, anim_rect)
        # 绘制按钮
        self._draw_buttons(target, anim_rect)

    # ── 内部绘制 ─────────────────────────────────────────────────

    def _draw_dialog_box(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
    ) -> None:
        """绘制对话框主体。"""
        # 外发光效果
        glow_surf = pygame.Surface(
            (rect.width + 16, rect.height + 16), pygame.SRCALPHA
        )
        pygame.draw.rect(
            glow_surf,
            (*_DIALOG_BG, 80),
            pygame.Rect(8, 8, rect.width, rect.height),
            border_radius=16,
        )
        surface.blit(glow_surf, (rect.x - 8, rect.y - 8))

        # 主背景
        pygame.draw.rect(surface, _DIALOG_BG, rect, border_radius=12)

        # 渐变顶部条
        gradient_h = min(50, rect.height // 4)
        for y in range(gradient_h):
            ratio = y / gradient_h
            r = int(_DIALOG_BG[0] + (_DIALOG_BG_LIGHT[0] - _DIALOG_BG[0]) * ratio)
            g = int(_DIALOG_BG[1] + (_DIALOG_BG_LIGHT[1] - _DIALOG_BG[1]) * ratio)
            b = int(_DIALOG_BG[2] + (_DIALOG_BG_LIGHT[2] - _DIALOG_BG[2]) * ratio)
            pygame.draw.line(
                surface, (r, g, b),
                (rect.x + 6, rect.y + y),
                (rect.x + rect.width - 6, rect.y + y),
            )

        # 白色边框
        pygame.draw.rect(surface, _DIALOG_BORDER, rect, width=3, border_radius=12)

        # 内部阴影
        inner_rect = rect.inflate(-6, -6)
        pygame.draw.rect(
            surface, (30, 30, 50), inner_rect, width=1, border_radius=8
        )

    def _draw_content(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
    ) -> None:
        """绘制对话框内容文字。"""
        # 顶部标题
        title_font = self._get_font(22, bold=True)
        title_text = "⚔️  选择出牌顺序"
        title_surf = title_font.render(title_text, True, _TEXT_COLOR)
        title_rect = title_surf.get_rect(
            centerx=rect.centerx,
            y=rect.y + 20,
        )
        # 阴影
        shadow = title_font.render(title_text, True, _SHADOW_COLOR)
        surface.blit(shadow, (title_rect.x + 2, title_rect.y + 2))
        surface.blit(title_surf, title_rect)

        # 分隔线
        line_y = rect.y + 58
        pygame.draw.line(
            surface, (200, 200, 220, 100),
            (rect.x + 30, line_y),
            (rect.right - 30, line_y),
            2,
        )

        # 先手说明
        first_font = self._get_font(16, bold=True)
        first_color = (130, 255, 130)  # 浅绿
        first_surf = first_font.render("先手出牌", True, first_color)
        first_rect = first_surf.get_rect(
            centerx=rect.centerx - 100, y=line_y + 20
        )
        surface.blit(first_surf, first_rect)

        desc_font = self._get_font(13)
        desc1 = desc_font.render("您先出牌，AI 后出", True, (180, 180, 200))
        desc1_rect = desc1.get_rect(
            centerx=rect.centerx - 100, y=line_y + 45
        )
        surface.blit(desc1, desc1_rect)

        # 后手说明
        second_color = (130, 180, 255)  # 浅蓝
        second_surf = first_font.render("后手出牌", True, second_color)
        second_rect = second_surf.get_rect(
            centerx=rect.centerx + 100, y=line_y + 20
        )
        surface.blit(second_surf, second_rect)

        desc2 = desc_font.render("AI 先出牌，您后出", True, (180, 180, 200))
        desc2_rect = desc2.get_rect(
            centerx=rect.centerx + 100, y=line_y + 45
        )
        surface.blit(desc2, desc2_rect)

        # 提示文字
        hint_font = self._get_font(13)
        hint_text = "选择将决定整场比赛的出牌顺序"
        hint_surf = hint_font.render(hint_text, True, _GOLD_COLOR)
        hint_rect = hint_surf.get_rect(
            centerx=rect.centerx, y=line_y + 80
        )
        surface.blit(hint_surf, hint_rect)

    def _draw_buttons(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
    ) -> None:
        """绘制先手和后手按钮。"""
        # 先手按钮（绿色）
        self._draw_button(
            surface,
            self._first_btn,
            "🗡️ 先手",
            _BTN_FIRST,
            self._first_hover,
        )

        # 后手按钮（蓝色）
        self._draw_button(
            surface,
            self._second_btn,
            "🛡️ 后手",
            _BTN_SECOND,
            self._second_hover,
        )

    def _draw_button(
        self,
        surface: pygame.Surface,
        btn_rect: pygame.Rect,
        label: str,
        base_color: tuple[int, int, int],
        is_hover: bool,
    ) -> None:
        """绘制单个按钮。"""
        if is_hover:
            offset = -_BTN_HOVER_OFFSET // 2
            draw_rect = btn_rect.inflate(offset, offset)
            bg_color = tuple(min(255, c + 30) for c in base_color)
        else:
            draw_rect = btn_rect
            bg_color = base_color

        pygame.draw.rect(surface, bg_color, draw_rect, border_radius=8)
        border_color = (255, 255, 255) if is_hover else (200, 200, 200)
        pygame.draw.rect(surface, border_color, draw_rect, width=2, border_radius=8)

        btn_font = self._get_font(16, bold=True)
        text_surf = btn_font.render(label, True, (255, 255, 255))
        text_rect = text_surf.get_rect(center=draw_rect.center)
        surface.blit(text_surf, text_rect)

    # ── 字体缓存 ─────────────────────────────────────────────────

    def _get_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (max(8, size), bold)
        if key not in self._font_cache:
            if not pygame.font.get_init():
                pygame.font.init()
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
