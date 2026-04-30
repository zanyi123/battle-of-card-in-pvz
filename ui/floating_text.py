"""ui/floating_text.py - 飘字系统。

伤害/治疗数值浮动显示，独立管理器负责生命周期与渲染，避免内存泄漏。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import pygame


@dataclass
class FloatingText:
    """单条飘字实例。"""

    text: str
    x: int
    y: int
    vx: float = 2.5
    vy: float = -2.5
    lifetime: float = 1.0
    age: float = 0.0
    color: Tuple[int, int, int] = (255, 51, 51)
    font_size: int = 26
    alpha: int = 255

    def update(self, dt: float) -> None:
        """每帧更新位置、年龄与透明度。"""
        self.age += dt
        self.x += self.vx
        self.y += self.vy
        ratio = max(0.0, 1.0 - self.age / self.lifetime)
        self.alpha = int(255 * ratio)

    @property
    def is_dead(self) -> bool:
        return self.age >= self.lifetime


class FloatingTextManager:
    """飘字管理器，维护活跃飘字列表并自动回收。"""

    def __init__(self, font_getter=None) -> None:
        self._texts: List[FloatingText] = []
        self._font_getter = font_getter

    def add_text(
        self,
        text: str,
        x: int,
        y: int,
        color: Tuple[int, int, int] = (255, 51, 51),
        font_size: int = 26,
    ) -> None:
        """添加一条飘字。"""
        self._texts.append(
            FloatingText(
                text=text,
                x=x,
                y=y,
                color=color,
                font_size=font_size,
            )
        )

    def update(self, dt: float) -> None:
        """更新所有飘字，移除已过期。"""
        for ft in self._texts:
            ft.update(dt)
        self._texts = [ft for ft in self._texts if not ft.is_dead]

    def render(self, surface: pygame.Surface) -> None:
        """渲染所有活跃飘字到目标 surface。"""
        if not self._texts:
            return

        if self._font_getter is None:
            font = pygame.font.Font(None, 26)
            font.set_bold(True)
        else:
            font = None  # 延迟获取

        for ft in self._texts:
            if ft.alpha <= 0:
                continue

            # 按需获取字体（每种 font_size 缓存一份）
            if self._font_getter is not None:
                font = self._font_getter(ft.font_size, bold=True)

            text_surf = font.render(ft.text, True, ft.color)

            # 通过 SRCALPHA 临时 surface 实现整体透明度
            w, h = text_surf.get_size()
            tmp = pygame.Surface((w, h), pygame.SRCALPHA)
            tmp.blit(text_surf, (0, 0))
            tmp.set_alpha(ft.alpha)

            surface.blit(tmp, (int(ft.x), int(ft.y)))

    @property
    def active_count(self) -> int:
        return len(self._texts)
