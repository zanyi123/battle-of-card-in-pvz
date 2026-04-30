"""ui/menu_interactions.py - 主菜单植物交互动画系统。

功能：
  - InteractivePlant 基类：状态机管理（IDLE / TRIGGERED / COOLDOWN）
  - PeashooterPlant：发射豌豆（贝塞尔曲线轨迹）
  - SunflowerPlant：挺身发光（叠加暖黄滤镜）
  - ChomperPlant：摇头（高频旋转，频率可调）
  - SquashPlant：眼睛跟踪鼠标（视差位移效果）
  - Projectile 类：飞行豌豆管理（自动销毁）

按钮与植物映射关系：
  - 人机对战  → PeashooterPlant（豌豆射手）
  - 成就框    → SunflowerPlant（向日葵）
  - 二人对战  → ChomperPlant（大嘴花）
  - 右下角    → SquashPlant（窝瓜）

状态转换：
  IDLE ──(hover+无冷却)──▶ TRIGGERED ──(4秒)──▶ COOLDOWN ──(5秒)──▶ IDLE
                                ▲                    │
                                └────────────────────┘
"""
from __future__ import annotations

import math
from enum import Enum, auto
from typing import Any, Optional

import pygame


# ── 常量配置 ────────────────────────────────────────────────────────
_ANIM_DURATION_MS: int = 4000   # 特殊动画持续时间（毫秒）
_COOLDOWN_DURATION_MS: int = 5000  # 冷却时间（毫秒）
_IDLE_BOB_SPEED: float = 1.2   # 呼吸动画频率（Hz）
_IDLE_BOB_AMPLITUDE: float = 3.0  # 呼吸上下幅度（像素）


def _ease_out_cubic(t: float) -> float:
    """三次缓出函数。"""
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out_sine(t: float) -> float:
    """正弦缓入缓出。"""
    return -(math.cos(math.pi * t) - 1.0) / 2.0


# ── Projectile 类 ───────────────────────────────────────────────────

class Projectile:
    """飞行豌豆：绿色圆形 + 拖尾效果，自动销毁。"""

    TRAIL_LENGTH: int = 8

    def __init__(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        duration_ms: int = 600,
    ) -> None:
        self.start_x = start_x
        self.start_y = start_y
        self.end_x = end_x
        self.end_y = end_y
        self.duration_ms = duration_ms
        self.start_time_ms: int = 0
        self.alive: bool = True
        self.trail: list[tuple[float, float]] = []

    def launch(self, current_time_ms: int) -> None:
        """开始飞行。"""
        self.start_time_ms = current_time_ms
        self.alive = True
        self.trail.clear()

    @property
    def progress(self) -> float:
        """当前飞行进度 [0, 1]。"""
        if self.start_time_ms == 0:
            return 0.0
        elapsed = pygame.time.get_ticks() - self.start_time_ms
        return min(elapsed / self.duration_ms, 1.0)

    def get_position(self) -> tuple[float, float]:
        """获取当前位置（贝塞尔曲线轨迹）。"""
        t = _ease_out_cubic(self.progress)
        # 二次贝塞尔曲线：控制点在起点上方
        ctrl_x = (self.start_x + self.end_x) / 2.0
        ctrl_y = min(self.start_y, self.end_y) - 150.0  # 曲线上凸
        x = (1 - t) ** 2 * self.start_x + 2 * (1 - t) * t * ctrl_x + t**2 * self.end_x
        y = (1 - t) ** 2 * self.start_y + 2 * (1 - t) * t * ctrl_y + t**2 * self.end_y
        return x, y

    def update(self) -> None:
        """每帧更新：记录轨迹点，检测销毁。"""
        if not self.alive or self.start_time_ms == 0:
            return
        x, y = self.get_position()
        self.trail.append((x, y))
        if len(self.trail) > self.TRAIL_LENGTH:
            self.trail.pop(0)
        if self.progress >= 1.0:
            self.alive = False

    def draw(self, surface: pygame.Surface) -> None:
        """绘制豌豆 + 拖尾。"""
        if not self.alive or not self.trail:
            return
        # 拖尾（渐变透明）
        for i, (tx, ty) in enumerate(self.trail[:-1]):
            alpha = int(200 * (i / len(self.trail)))
            radius = max(3, int(8 * (i / len(self.trail))))
            trail_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(trail_surf, (80, 200, 80, alpha), (radius, radius), radius)
            surface.blit(trail_surf, (int(tx) - radius, int(ty) - radius))
        # 主豌豆
        px, py = self.trail[-1]
        radius = 10
        pygame.draw.circle(surface, (60, 180, 60), (int(px), int(py)), radius)
        pygame.draw.circle(surface, (100, 240, 100), (int(px), int(py)), radius)
        pygame.draw.circle(surface, (30, 120, 30), (int(px) - 3, int(py) - 3), 3)


# ── PlantState 枚举 ─────────────────────────────────────────────────

class PlantState(Enum):
    """植物状态枚举。"""
    IDLE = auto()       # 默认呼吸
    TRIGGERED = auto()  # 触发特殊动画
    COOLDOWN = auto()   # 冷却锁定


# ── InteractivePlant 基类 ───────────────────────────────────────────

class InteractivePlant:
    """可交互植物基类：状态机 + 呼吸动画 + 冷却系统。"""

    def __init__(
        self,
        screen_w: int,
        screen_h: int,
        base_x: int,
        base_y: int,
        anim_duration_ms: int = _ANIM_DURATION_MS,
        cooldown_ms: int = _COOLDOWN_DURATION_MS,
    ) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.base_x = base_x       # 原始 x 坐标
        self.base_y = base_y       # 原始 y 坐标
        self.anim_duration_ms = anim_duration_ms
        self.cooldown_ms = cooldown_ms

        self.state: PlantState = PlantState.IDLE
        self.state_entered_at_ms: int = 0
        self.idle_time: float = 0.0  # 累计空闲时间（秒）
        self.trigger_count: int = 0  # 调试用

        # 可被覆写的偏移量
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0

    @property
    def draw_x(self) -> int:
        """实际绘制 x 坐标。"""
        return int(self.base_x + self.offset_x)

    @property
    def draw_y(self) -> int:
        """实际绘制 y 坐标。"""
        return int(self.base_y + self.offset_y)

    def trigger_animation(self) -> None:
        """触发特殊动画（从 IDLE 或 COOLDOWN 均可触发）。"""
        if self.state is PlantState.TRIGGERED:
            return  # 已在播放
        self.state = PlantState.TRIGGERED
        self.state_entered_at_ms = pygame.time.get_ticks()
        self.trigger_count += 1
        print(f"[Plant] {self.__class__.__name__} 触发 #{self.trigger_count} | 剩余冷却 {self._cooldown_remaining():.1f}s")

    def _cooldown_remaining(self) -> float:
        """获取冷却剩余时间（秒）。"""
        if self.state is not PlantState.COOLDOWN:
            return 0.0
        elapsed = pygame.time.get_ticks() - self.state_entered_at_ms
        return max(0.0, (self.cooldown_ms - elapsed) / 1000.0)

    def update(self, dt: float) -> None:
        """每帧更新状态机。"""
        self.idle_time += dt

        if self.state is PlantState.IDLE:
            self._update_idle(dt)
        elif self.state is PlantState.TRIGGERED:
            elapsed = pygame.time.get_ticks() - self.state_entered_at_ms
            if elapsed >= self.anim_duration_ms:
                self.state = PlantState.COOLDOWN
                self.state_entered_at_ms = pygame.time.get_ticks()
            self._update_triggered(dt)
        elif self.state is PlantState.COOLDOWN:
            elapsed = pygame.time.get_ticks() - self.state_entered_at_ms
            if elapsed >= self.cooldown_ms:
                self.state = PlantState.IDLE
                self.idle_time = 0.0
            self._update_cooldown(dt)

    def _update_idle(self, dt: float) -> None:
        """IDLE 状态：呼吸动画。"""
        self.offset_y = math.sin(self.idle_time * _IDLE_BOB_SPEED * 2 * math.pi) * _IDLE_BOB_AMPLITUDE

    def _update_triggered(self, dt: float) -> None:
        """TRIGGERED 状态：子类实现特殊动画。"""
        raise NotImplementedError

    def _update_cooldown(self, dt: float) -> None:
        """COOLDOWN 状态：轻微回归原始位置。"""
        progress = min(1.0, (pygame.time.get_ticks() - self.state_entered_at_ms) / self.cooldown_ms)
        eased = _ease_out_cubic(progress)
        self.offset_y = (1.0 - eased) * self.offset_y
        self.offset_x = (1.0 - eased) * self.offset_x

    def draw(self, surface: pygame.Surface) -> None:
        """绘制植物，子类实现。"""
        raise NotImplementedError


# ── PeashooterPlant ─────────────────────────────────────────────────

class PeashooterPlant(InteractivePlant):
    """豌豆射手：hover 时发射豌豆飞向屏幕顶部。"""

    def __init__(self, screen_w: int, screen_h: int) -> None:
        # 茎部位置（背景图估算）
        base_x = int(screen_w * 0.083) + 10
        base_y = int(screen_h * 0.495) - 20
        super().__init__(screen_w, screen_h, base_x, base_y)

        self.recoil_offset: float = 0.0  # 后坐力
        self.projectiles: list[Projectile] = []
        self._mouth_offset_x: int = 50   # 嘴部相对 base_x 的偏移
        self._mouth_offset_y: int = -30  # 嘴部相对 base_y 的偏移

    @property
    def mouth_pos(self) -> tuple[float, float]:
        """嘴部世界坐标。"""
        return self.draw_x + self._mouth_offset_x, self.draw_y + self._mouth_offset_y

    def trigger_animation(self) -> None:
        """发射豌豆。"""
        super().trigger_animation()
        # 创建新豌豆
        mx, my = self.mouth_pos
        proj = Projectile(
            start_x=mx,
            start_y=my,
            end_x=self.screen_w / 2,
            end_y=0,
            duration_ms=600,
        )
        proj.launch(pygame.time.get_ticks())
        self.projectiles.append(proj)
        # 后坐力
        self.recoil_offset = -8.0

    def _update_triggered(self, dt: float) -> None:
        """后坐力恢复 + 更新豌豆。"""
        # 缓出恢复后坐力
        self.recoil_offset *= 0.92
        self.offset_x = self.recoil_offset
        # 更新所有豌豆
        for p in self.projectiles:
            p.update()
        # 清理死亡豌豆
        self.projectiles = [p for p in self.projectiles if p.alive]

    def draw(self, surface: pygame.Surface) -> None:
        """绘制豌豆射手（程序化渲染）。"""
        x, y = self.draw_x, self.draw_y

        # ── 茎（棕色矩形）─────────────────────────────────────────
        stem_w, stem_h = 12, 50
        stem_rect = pygame.Rect(x - stem_w // 2, y - 10, stem_w, stem_h)
        pygame.draw.rect(surface, (60, 100, 40), stem_rect, border_radius=4)

        # ── 头部（绿色圆形）───────────────────────────────────────
        head_cx = x + 20
        head_cy = y - 25
        head_r = 22
        pygame.draw.circle(surface, (60, 160, 60), (head_cx, head_cy), head_r)
        pygame.draw.circle(surface, (80, 200, 80), (head_cx, head_cy), head_r)

        # ── 眼睛（两个小白点）────────────────────────────────────
        eye_offset = 8
        pygame.draw.circle(surface, (255, 255, 255), (head_cx - eye_offset, head_cy - 5), 4)
        pygame.draw.circle(surface, (255, 255, 255), (head_cx + eye_offset, head_cy - 5), 4)
        pygame.draw.circle(surface, (0, 0, 0), (head_cx - eye_offset + 1, head_cy - 4), 2)
        pygame.draw.circle(surface, (0, 0, 0), (head_cx + eye_offset + 1, head_cy - 4), 2)

        # ── 嘴部（突出的嘴管）────────────────────────────────────
        mouth_x = head_cx + 15
        mouth_y = head_cy - 5
        pygame.draw.ellipse(surface, (50, 140, 50), (mouth_x, mouth_y - 5, 20, 12))
        pygame.draw.ellipse(surface, (80, 180, 80), (mouth_x + 2, mouth_y - 3, 16, 8))

        # ── 叶子（两侧小叶子）────────────────────────────────────
        leaf_points_left = [
            (x - 5, y + 10),
            (x - 20, y + 20),
            (x - 5, y + 30),
        ]
        leaf_points_right = [
            (x + 5, y + 15),
            (x + 25, y + 25),
            (x + 5, y + 35),
        ]
        if self.state is PlantState.TRIGGERED:
            glow_color = (150, 255, 150, 60)
            glow_surf = pygame.Surface((60, 60), pygame.SRCALPHA)
            pygame.draw.circle(glow_surf, glow_color, (30, 30), 30)
            surface.blit(glow_surf, (head_cx - 30, head_cy - 30))
        pygame.draw.polygon(surface, (70, 150, 70), leaf_points_left)
        pygame.draw.polygon(surface, (70, 150, 70), leaf_points_right)

        # ── 绘制所有飞行中的豌豆 ──────────────────────────────────
        for proj in self.projectiles:
            proj.draw(surface)


# ── SunflowerPlant ──────────────────────────────────────────────────

class SunflowerPlant(InteractivePlant):
    """向日葵：hover 时挺身 + 发光开心效果。"""

    def __init__(self, screen_w: int, screen_h: int) -> None:
        base_x = int(screen_w * 0.079) + 5
        base_y = int(screen_h * 0.768) - 30
        super().__init__(screen_w, screen_h, base_x, base_y)
        self._glow_alpha: float = 0.0  # 当前发光透明度
        self._scale: float = 1.0       # 当前缩放

    def trigger_animation(self) -> None:
        """挺身发光。"""
        super().trigger_animation()
        self._glow_alpha = 0.0
        self._scale = 1.0

    def _update_triggered(self, dt: float) -> None:
        """挺身 + 发光 + 复位动画。"""
        elapsed = pygame.time.get_ticks() - self.state_entered_at_ms
        progress = min(1.0, elapsed / self.anim_duration_ms)

        # 先快速挺身（0-30%）
        rise_progress = min(1.0, progress / 0.3)
        self.offset_y = -20.0 * _ease_out_cubic(rise_progress)
        self._scale = 1.0 + 0.1 * _ease_out_cubic(rise_progress)

        # 发光效果（30%-70% 峰值）
        if 0.3 <= progress <= 0.7:
            glow_progress = (progress - 0.3) / 0.4
            self._glow_alpha = 120.0 * math.sin(glow_progress * math.pi)
        else:
            self._glow_alpha = max(0.0, self._glow_alpha - 3.0)

        # 缓慢复位（70%-100%）
        if progress >= 0.7:
            reset_progress = (progress - 0.7) / 0.3
            eased = _ease_in_out_sine(reset_progress)
            self.offset_y = -20.0 * (1.0 - eased)
            self._scale = 1.0 + 0.1 * (1.0 - eased)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制向日葵（程序化渲染）。"""
        x, y = self.draw_x, self.draw_y
        scale = self._scale

        # ── 茎（棕色）───────────────────────────────────────────
        stem_w, stem_h = 10, 45
        stem_rect = pygame.Rect(
            x - stem_w // 2, y - 5,
            stem_w, int(stem_h * scale)
        )
        pygame.draw.rect(surface, (80, 60, 30), stem_rect, border_radius=3)

        # ── 叶子 ─────────────────────────────────────────────────
        leaf_pts = [
            (x - 5, y + 15),
            (x - 25, y + 25),
            (x - 5, y + 35),
        ]
        pygame.draw.polygon(surface, (60, 140, 40), leaf_pts)
        leaf_pts2 = [
            (x + 5, y + 20),
            (x + 28, y + 30),
            (x + 5, y + 40),
        ]
        pygame.draw.polygon(surface, (60, 140, 40), leaf_pts2)

        # ── 花瓣（金黄色）────────────────────────────────────────
        petal_count = 12
        petal_r_outer = int(20 * scale)
        petal_r_inner = int(12 * scale)
        petal_color = (255, 220, 50)

        cx, cy = x, int(y - 20 * scale)
        for i in range(petal_count):
            angle = (2 * math.pi * i / petal_count) - math.pi / 2
            px_outer = cx + int(petal_r_outer * math.cos(angle))
            py_outer = cy + int(petal_r_outer * math.sin(angle))
            px_inner = cx + int(petal_r_inner * math.cos(angle))
            py_inner = cy + int(petal_r_inner * math.sin(angle))
            pygame.draw.line(surface, petal_color, (px_inner, py_inner), (px_outer, py_outer), 4)

        # ── 花心（棕色圆形）──────────────────────────────────────
        face_r = int(14 * scale)
        pygame.draw.circle(surface, (100, 60, 20), (cx, cy), face_r)
        pygame.draw.circle(surface, (140, 80, 30), (cx, cy), face_r)

        # ── 表情（开心）──────────────────────────────────────────
        smile_y = cy + 2
        # 眼睛
        eye_offset = 5
        pygame.draw.circle(surface, (0, 0, 0), (cx - eye_offset, smile_y - 3), 2)
        pygame.draw.circle(surface, (0, 0, 0), (cx + eye_offset, smile_y - 3), 2)
        # 微笑
        smile_pts = [
            (cx - 6, smile_y + 2),
            (cx, smile_y + 6),
            (cx + 6, smile_y + 2),
        ]
        pygame.draw.lines(surface, (0, 0, 0), False, smile_pts, 2)

        # ── 发光效果（叠加暖黄滤镜）──────────────────────────────
        if self._glow_alpha > 0:
            glow_surf = pygame.Surface((80, 80), pygame.SRCALPHA)
            glow_color = (255, 220, 80, int(self._glow_alpha))
            pygame.draw.circle(glow_surf, glow_color, (40, 40), 40)
            surface.blit(glow_surf, (cx - 40, cy - 40))


# ── ChomperPlant ────────────────────────────────────────────────────

class ChomperPlant(InteractivePlant):
    """大嘴花：hover 时剧烈摇头（频率可调）。"""

    # 摇头参数（降低频率避免卡顿）
    SWING_AMPLITUDE_DEG: float = 15.0   # 振幅（度）
    SWING_FREQUENCY_HZ: float = 2.0     # 频率（Hz），降低到 2Hz 避免卡顿

    def __init__(self, screen_w: int, screen_h: int) -> None:
        base_x = int(screen_w * 0.156) + 30
        base_y = int(screen_h * 0.638) - 20
        super().__init__(screen_w, screen_h, base_x, base_y)
        self._rotation_angle: float = 0.0
        self._anim_start_time: float = 0.0  # 动画开始时间

    def trigger_animation(self) -> None:
        """开始摇头。"""
        super().trigger_animation()
        self._anim_start_time = self.idle_time

    def _update_triggered(self, dt: float) -> None:
        """摇头动画。"""
        elapsed = self.idle_time - self._anim_start_time
        self._rotation_angle = self.SWING_AMPLITUDE_DEG * math.sin(
            elapsed * self.SWING_FREQUENCY_HZ * 2 * math.pi
        )
        # 动画快结束时逐渐减小振幅
        progress = min(1.0, (pygame.time.get_ticks() - self.state_entered_at_ms) / self.anim_duration_ms)
        if progress > 0.7:
            fade = (1.0 - progress) / 0.3
            self._rotation_angle *= fade

    def _update_idle(self, dt: float) -> None:
        """IDLE：轻微呼吸摆动。"""
        super()._update_idle(dt)
        # 额外轻微摇头（幅值很小）
        self._rotation_angle = 2.0 * math.sin(self.idle_time * 0.8 * 2 * math.pi)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制大嘴花（程序化渲染，旋转基点为茎底部）。"""
        # 旋转中心点（茎底部）
        pivot_x = self.draw_x
        pivot_y = self.draw_y + 20  # 茎底部

        # 创建临时 surface 用于旋转
        temp_size = max(self.screen_w, self.screen_h) * 2
        temp = pygame.Surface((temp_size, temp_size), pygame.SRCALPHA)
        temp.fill((0, 0, 0, 0))

        local_x = temp_size // 2
        local_y = temp_size // 2 - 20  # 植物相对临时 surface 的位置

        # ── 绘制到临时 surface ────────────────────────────────────
        # 茎
        stem_w, stem_h = 14, 55
        stem_rect = pygame.Rect(local_x - stem_w // 2, local_y, stem_w, stem_h)
        pygame.draw.rect(temp, (60, 120, 50), stem_rect, border_radius=5)

        # 叶子
        leaf_pts1 = [(local_x - 7, local_y + 20), (local_x - 30, local_y + 35), (local_x - 7, local_y + 45)]
        leaf_pts2 = [(local_x + 7, local_y + 25), (local_x + 35, local_y + 40), (local_x + 7, local_y + 50)]
        pygame.draw.polygon(temp, (50, 150, 50), leaf_pts1)
        pygame.draw.polygon(temp, (50, 150, 50), leaf_pts2)

        # 头部（大嘴）
        head_cx = local_x
        head_cy = local_y - 15
        head_r = 28
        pygame.draw.circle(temp, (50, 150, 50), (head_cx, head_cy), head_r)
        pygame.draw.circle(temp, (70, 180, 70), (head_cx, head_cy), head_r)

        # 眼睛
        eye_offset = 10
        pygame.draw.circle(temp, (255, 255, 255), (head_cx - eye_offset, head_cy - 5), 6)
        pygame.draw.circle(temp, (255, 255, 255), (head_cx + eye_offset, head_cy - 5), 6)
        pygame.draw.circle(temp, (0, 0, 0), (head_cx - eye_offset + 2, head_cy - 4), 3)
        pygame.draw.circle(temp, (0, 0, 0), (head_cx + eye_offset + 2, head_cy - 4), 3)

        # 大嘴（下半圆）
        mouth_r = 18
        mouth_rect = pygame.Rect(
            head_cx - mouth_r, head_cy + 5, mouth_r * 2, mouth_r
        )
        pygame.draw.rect(temp, (30, 80, 30), mouth_rect)
        pygame.draw.arc(
            temp, (40, 100, 40),
            (head_cx - mouth_r, head_cy, mouth_r * 2, mouth_r * 2),
            0, math.pi, 3
        )
        # 牙齿
        for i in range(3):
            tooth_x = head_cx - 12 + i * 12
            tooth_rect = pygame.Rect(tooth_x, head_cy + 3, 8, 10)
            pygame.draw.rect(temp, (255, 255, 220), tooth_rect)

        # 旋转
        rotated = pygame.transform.rotate(temp, -self._rotation_angle)
        rot_rect = rotated.get_rect(center=(pivot_x, pivot_y))
        surface.blit(rotated, rot_rect)


# ── SquashPlant ─────────────────────────────────────────────────────

class SquashPlant(InteractivePlant):
    """窝瓜：hover 时眼睛跟踪鼠标（视差位移效果）。"""

    def __init__(self, screen_w: int, screen_h: int) -> None:
        # 窝瓜位置：右下角按钮组正上方
        base_x = int(screen_w * 0.81) - 40
        base_y = int(screen_h * 0.88) - 60
        super().__init__(screen_w, screen_h, base_x, base_y)
        self._parallax_x: float = 0.0
        self._parallax_y: float = 0.0
        self._eye_angle: float = 0.0

    def trigger_animation(self) -> None:
        """触发视差注视效果。"""
        super().trigger_animation()

    def _update_triggered(self, dt: float) -> None:
        """计算鼠标-窝瓜向量，产生视差位移。"""
        mx, my = pygame.mouse.get_pos()
        dx = mx - self.base_x
        dy = my - self.base_y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist > 1:
            # 视差位移（最大 10px）
            max_parallax = 10.0
            self._parallax_x = (dx / dist) * min(max_parallax, dist / 20)
            self._parallax_y = (dy / dist) * min(max_parallax, dist / 20)
            # 眼睛看向方向的角度
            self._eye_angle = math.atan2(dy, dx)
        else:
            self._parallax_x = 0.0
            self._parallax_y = 0.0

        self.offset_x = self._parallax_x
        self.offset_y = self._parallax_y

        # 动画快结束时复位
        progress = min(1.0, (pygame.time.get_ticks() - self.state_entered_at_ms) / self.anim_duration_ms)
        if progress > 0.7:
            fade = (1.0 - progress) / 0.3
            self.offset_x *= fade
            self.offset_y *= fade

    def _update_idle(self, dt: float) -> None:
        """轻微呼吸效果。"""
        super()._update_idle(dt)
        # 额外轻微左右微动
        self.offset_x = 1.5 * math.sin(self.idle_time * 0.5 * 2 * math.pi)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制窝瓜（程序化渲染）。"""
        x, y = self.draw_x, self.draw_y

        # ── 身体（椭圆形，绿色）───────────────────────────────────
        body_w, body_h = 50, 65
        body_rect = pygame.Rect(x - body_w // 2, y - body_h, body_w, body_h)
        pygame.draw.ellipse(surface, (80, 140, 40), body_rect)
        pygame.draw.ellipse(surface, (100, 170, 60), body_rect)

        # 身体纹理
        for i in range(3):
            vein_x = x - 15 + i * 15
            pygame.draw.line(
                surface, (60, 120, 30),
                (vein_x, y - body_h + 10),
                (vein_x, y - 10), 2
            )

        # ── 叶子（头顶小叶子）─────────────────────────────────────
        leaf_pts = [
            (x, y - body_h - 5),
            (x - 15, y - body_h - 20),
            (x - 5, y - body_h - 10),
        ]
        pygame.draw.polygon(surface, (60, 140, 40), leaf_pts)
        leaf_pts2 = [
            (x + 5, y - body_h - 8),
            (x + 20, y - body_h - 18),
            (x + 8, y - body_h - 5),
        ]
        pygame.draw.polygon(surface, (60, 140, 40), leaf_pts2)

        # ── 眼睛（聚焦光斑效果）──────────────────────────────────
        eye_cx = x
        eye_cy = y - body_h // 2 - 5

        # 眼白
        eye_r = 14
        pygame.draw.ellipse(surface, (255, 255, 220), (eye_cx - eye_r, eye_cy - eye_r, eye_r * 2, eye_r * 2))

        # 瞳孔（根据鼠标位置偏移）
        pupil_offset = 4
        pupil_x = eye_cx + int(pupil_offset * math.cos(self._eye_angle))
        pupil_y = eye_cy + int(pupil_offset * math.sin(self._eye_angle))
        pupil_r = 6
        pygame.draw.circle(surface, (20, 20, 20), (pupil_x, pupil_y), pupil_r)
        pygame.draw.circle(surface, (50, 50, 50), (pupil_x, pupil_y), pupil_r)

        # 聚焦光斑
        highlight_x = pupil_x - 2
        highlight_y = pupil_y - 2
        pygame.draw.circle(surface, (255, 255, 255), (highlight_x, highlight_y), 2)

        # ── 嘴巴（微笑）──────────────────────────────────────────
        mouth_y = eye_cy + 18
        smile_pts = [
            (x - 12, mouth_y),
            (x, mouth_y + 8),
            (x + 12, mouth_y),
        ]
        pygame.draw.arc(
            surface, (20, 60, 20),
            (x - 15, mouth_y - 5, 30, 15),
            0.2, math.pi - 0.2, 3
        )

        # ── 聚焦光斑效果（整体轻微发光）──────────────────────────
        if self.state is PlantState.TRIGGERED:
            glow_surf = pygame.Surface((body_w + 30, body_h + 30), pygame.SRCALPHA)
            glow_color = (150, 255, 150, 40)
            pygame.draw.ellipse(glow_surf, glow_color, (0, 0, body_w + 30, body_h + 30))
            surface.blit(glow_surf, (x - body_w // 2 - 15, y - body_h - 15))


# ── PlantInteractionManager ────────────────────────────────────────

class PlantInteractionManager:
    """植物交互管理器：维护所有植物对象 + 按钮映射 + 冷却检测。"""

    def __init__(self, screen_w: int, screen_h: int) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h

        # 创建植物实例
        self.plants: dict[str, InteractivePlant] = {
            "pve": PeashooterPlant(screen_w, screen_h),
            "achievement": SunflowerPlant(screen_w, screen_h),
            "pvp": ChomperPlant(screen_w, screen_h),
            "squash": SquashPlant(screen_w, screen_h),
        }

        # 按钮区域与植物 key 的映射
        self.button_plant_map: dict[str, str] = {
            "pve": "pve",        # 人机对战 → 豌豆射手
            "achievement": "achievement",  # 成就框 → 向日葵
            "pvp": "pvp",        # 二人对战 → 大嘴花
            "squash": "squash",  # 右下角 → 窝瓜
        }

    def update(self, dt: float, button_rects: dict[str, pygame.Rect]) -> None:
        """每帧更新所有植物 + 检测悬停触发。"""
        mouse_pos = pygame.mouse.get_pos()

        for btn_key, plant_key in self.button_plant_map.items():
            plant = self.plants.get(plant_key)
            if plant is None:
                continue

            # 检测是否悬停对应按钮
            btn_rect = button_rects.get(btn_key)
            is_hover = btn_rect is not None and btn_rect.collidepoint(mouse_pos)

            if is_hover and plant.state is PlantState.IDLE:
                plant.trigger_animation()

        # 更新所有植物状态
        for plant in self.plants.values():
            plant.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制所有植物。"""
        for plant in self.plants.values():
            plant.draw(surface)
