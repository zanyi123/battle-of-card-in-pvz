"""ui/confirm_dialog.py - PVZ 植物卡牌对战确认对话框。

提供：
  - ConfirmDialog 类：蓝底白字模态弹窗
  - 确认出征 / 取消 两个按钮
  - show() / hide() / handle_event() / draw() 标准接口
  - 确认时返回 (True, world_name)；取消返回 (False, None)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import pygame

from utils.path_utils import get_resource_path


# ── 颜色常量 ─────────────────────────────────────────────────────
_DIALOG_BG: tuple[int, int, int] = (41, 128, 185)      # 蓝底 #2980b9
_DIALOG_BG_LIGHT: tuple[int, int, int] = (52, 152, 219)  # 浅蓝高亮
_DIALOG_BORDER: tuple[int, int, int] = (255, 255, 255)  # 白边框
_TEXT_COLOR: tuple[int, int, int] = (255, 255, 255)    # 白字
_SHADOW_COLOR: tuple[int, int, int] = (0, 0, 0)        # 阴影

# 按钮颜色
_BTN_CONFIRM: tuple[int, int, int] = (39, 174, 96)     # 绿色确认
_BTN_CANCEL: tuple[int, int, int] = (192, 57, 43)      # 红色取消
_BTN_HOVER_OFFSET: int = 10


class ConfirmDialog:
    """阵前曲确认对话框。

    居中蓝底模态弹窗，用于玩家确认进入对战并触发阵前曲。

    用法::

        dialog = ConfirmDialog(screen, screen_size, on_confirm_callback)
        dialog.show("Neon Mixtape Tour")
        while dialog.visible:
            dialog.draw(screen)
            pygame.display.flip()
            for event in pygame.event.get():
                dialog.handle_event(event)
        result, world = dialog.result  # (True, world_name) or (False, None)
    """

    def __init__(
        self,
        screen: pygame.Surface,
        screen_size: tuple[int, int],
        on_confirm: Optional[Callable[[str], None]] = None,
    ) -> None:
        """初始化确认对话框。

        Args:
            screen:         pygame 屏幕 surface
            screen_size:    (width, height)
            on_confirm:     确认回调，签名为 (world_name: str) -> None
        """
        self.screen = screen
        self.screen_w, self.screen_h = screen_size
        self.on_confirm = on_confirm

        # 弹窗尺寸
        dlg_w, dlg_h = 420, 260
        self._dlg_rect = pygame.Rect(
            (screen_size[0] - dlg_w) // 2,
            (screen_size[1] - dlg_h) // 2,
            dlg_w, dlg_h,
        )

        # 按钮尺寸
        btn_w, btn_h = 140, 46
        btn_spacing = 30
        total_btn_w = 2 * btn_w + btn_spacing
        btn_start_x = self._dlg_rect.centerx - total_btn_w // 2
        btn_y = self._dlg_rect.bottom - btn_h - 24

        self._confirm_btn = pygame.Rect(btn_start_x, btn_y, btn_w, btn_h)
        self._cancel_btn = pygame.Rect(btn_start_x + btn_w + btn_spacing, btn_y, btn_w, btn_h)

        # 状态
        self.visible = False
        self.result: tuple[bool, Optional[str]] = (False, None)  # (confirmed, world_name)
        self._world_name: str = ""

        # 悬停状态
        self._confirm_hover: bool = False
        self._cancel_hover: bool = False

        # 动画状态
        self._anim_progress: float = 0.0  # 0→1 弹出动画
        self._animating: bool = False

        # 字体缓存
        self._font_cache: dict[int, pygame.font.Font] = {}

    # ── 公共接口 ─────────────────────────────────────────────────

    def show(self, world_name: str = "") -> None:
        """显示对话框。

        Args:
            world_name: 世界名称（显示在标题中）
        """
        self.visible = True
        self._world_name = world_name
        self.result = (False, None)
        self._confirm_hover = False
        self._cancel_hover = False
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
            self._confirm_hover = self._confirm_btn.collidepoint(mx, my)
            self._cancel_hover = self._cancel_btn.collidepoint(mx, my)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if self._confirm_btn.collidepoint(mx, my):
                self._on_confirm()
            elif self._cancel_btn.collidepoint(mx, my):
                self._on_cancel()

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_y):
                self._on_confirm()
            elif event.key in (pygame.K_ESCAPE, pygame.K_n):
                self._on_cancel()

    def update(self, dt: float) -> None:
        """更新动画。"""
        if self._animating:
            self._anim_progress = min(1.0, self._anim_progress + dt * 6.0)
            if self._anim_progress >= 1.0:
                self._animating = False

    def draw(self, surface: Optional[pygame.Surface] = None) -> None:
        """绘制确认对话框。"""
        if not self.visible:
            return

        target = surface if surface is not None else self.screen

        # 半透明遮罩
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        target.blit(overlay, (0, 0))

        # 弹出动画插值
        if self._animating:
            # 简单的弹性缩放动画
            t = self._anim_progress
            scale = 0.5 + 0.5 * t + 0.1 * (1.0 - t) * (1.0 - (1.0 - t) * (1.0 - t))
            scale = max(0.1, min(1.0, scale))
        else:
            scale = 1.0

        # 计算缩放后的矩形
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
        glow_surf = pygame.Surface((rect.width + 16, rect.height + 16), pygame.SRCALPHA)
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
            pygame.draw.line(surface, (r, g, b),
                            (rect.x + 6, rect.y + y),
                            (rect.x + rect.width - 6, rect.y + y))

        # 白色边框
        pygame.draw.rect(surface, _DIALOG_BORDER, rect, width=3, border_radius=12)

        # 内部阴影
        inner_rect = rect.inflate(-6, -6)
        pygame.draw.rect(surface, (20, 60, 100), inner_rect, width=1, border_radius=8)

    def _draw_content(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
    ) -> None:
        """绘制对话框内容文字。"""
        # 顶部标题
        title_font = self._get_font(22, bold=True)
        title_text = "⚔️  准备出征！" if self._world_name else "⚔️  确认出征"
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
        line_y = rect.y + 60
        pygame.draw.line(
            surface,
            (255, 255, 255, 100),
            (rect.x + 30, line_y),
            (rect.right - 30, line_y),
            2,
        )

        # 世界名称（如果有）
        if self._world_name:
            world_font = self._get_font(28, bold=True)
            world_color = (255, 235, 100)  # 金黄色
            world_surf = world_font.render(f"🌍 {self._world_name}", True, world_color)
            world_rect = world_surf.get_rect(centerx=rect.centerx, y=line_y + 20)
            surface.blit(world_surf, world_rect)

        # 主提示文字
        msg_font = self._get_font(16)
        msg_text = "与 AI 对战并获取胜利"
        msg_surf = msg_font.render(msg_text, True, (220, 235, 255))
        msg_rect = msg_surf.get_rect(
            centerx=rect.centerx,
            y=(line_y + 65) if self._world_name else (line_y + 30),
        )
        surface.blit(msg_surf, msg_rect)

    def _draw_buttons(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
    ) -> None:
        """绘制确认和取消按钮。"""
        # 确认按钮（绿色）
        self._draw_button(
            surface,
            self._confirm_btn,
            "✅ 确认出征",
            _BTN_CONFIRM,
            self._confirm_hover,
        )

        # 取消按钮（红色）
        self._draw_button(
            surface,
            self._cancel_btn,
            "❌ 取消",
            _BTN_CANCEL,
            self._cancel_hover,
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
        # 悬停放大效果
        if is_hover:
            offset_x = -_BTN_HOVER_OFFSET // 2
            offset_y = -_BTN_HOVER_OFFSET // 2
            draw_rect = btn_rect.inflate(offset_x, offset_y)
            bg_color = tuple(min(255, c + 30) for c in base_color)
        else:
            draw_rect = btn_rect
            bg_color = base_color

        # 按钮背景
        pygame.draw.rect(surface, bg_color, draw_rect, border_radius=8)

        # 按钮边框
        border_color = (255, 255, 255) if is_hover else (200, 200, 200)
        pygame.draw.rect(surface, border_color, draw_rect, width=2, border_radius=8)

        # 按钮文字
        btn_font = self._get_font(16, bold=True)
        text_surf = btn_font.render(label, True, (255, 255, 255))
        text_rect = text_surf.get_rect(center=draw_rect.center)
        surface.blit(text_surf, text_rect)

    # ── 事件处理 ─────────────────────────────────────────────────

    def _on_confirm(self) -> None:
        """确认按钮点击。"""
        self.result = (True, self._world_name)
        if self.on_confirm is not None:
            self.on_confirm(self._world_name)
        self.hide()

    def _on_cancel(self) -> None:
        """取消按钮点击。"""
        self.result = (False, None)
        self.hide()

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
