"""ui/menu_overlay.py - 主菜单植物交互热区特效系统。

【核心原则：单图坐标覆盖渲染】
- 严禁加载任何独立植物PNG素材
- 严禁操作背景图（transform.rotate/scale）
- 所有动效通过坐标覆盖层（Overlay）在原图上绘制

【渲染层级】
  背景大图 → 植物交互动效层（Overlay） → UI按钮层

【四植物特效实现】
  1. 🌻 向日葵（悬停"成就框"）：
     - 径向渐变光晕呼吸（中心亮黄，边缘透明）
     - 半径 40~70px 正弦脉动，透明度 0.4~0.7

  2. 🟢 豌豆射手（悬停"人机对战"）：
     - 从嘴部发射绿色粒子，沿贝塞尔曲线飞向屏幕顶部
     - 半透明拖尾，飞出屏幕自动销毁
     - 发射瞬间白色闪光环（后坐力）

  3. 🟣 大嘴花（悬停"二人对战"）：
     - 高频残影覆盖模拟摇头
     - 快速绘制半透明条纹按正弦偏移（±6px）
     - 结束后残影淡出

  4. 🍈 窝瓜（悬停右下角任意按钮）：
     - 瞳孔追踪鼠标向量角度（最大偏移5px）
     - 鼠标离开后0.5s缓动回正

【状态机】
  IDLE ──(hover)──▶ ACTIVE(4秒) ──▶ COOLDOWN(5秒) ──▶ IDLE
                              ▲              │
                              └──────────────┘

【按钮-植物映射】
  - 人机对战 → PeashooterEffect（PEASHOOTER_MOUTH）
  - 成就框   → SunflowerEffect（SUNFLOWER_POS）
  - 二人对战 → ChomperEffect（CHOMPER_FACE）
  - 右下角   → SquashEffect（SQUASH_EYES）
"""
from __future__ import annotations

import math
from enum import Enum, auto
from typing import Optional

import pygame


# ── 动画参数 ────────────────────────────────────────────────────────
_ANIM_DURATION_MS: int = 4000    # 特效持续时间（毫秒）
_COOLDOWN_DURATION_MS: int = 5000  # 冷却时间（毫秒）
_RETRIEVE_DURATION_S: float = 0.5  # 窝瓜瞳孔回正时长（秒）


# ── 热区坐标定义（初始占位，可通过 set_hotspot 微调）─────────────────
# 所有坐标基于 1024x768 基准背景图
class Hotspots:
    """植物交互热区坐标管理器。"""

    # 向日葵面部区域（成就框按钮对应）
    SUNFLOWER_POS: tuple[int, int, int, int] = (60, 570, 80, 80)

    # 豌豆射手嘴部坐标（人机对战按钮对应）
    PEASHOOTER_MOUTH: tuple[int, int] = (95, 350)

    # 大嘴花面部区域（二人对战按钮对应）
    CHOMPER_FACE: tuple[int, int, int, int] = (140, 470, 60, 50)

    # 窝瓜左右眼中心坐标（右下角按钮对应）
    SQUASH_EYES: tuple[tuple[int, int], tuple[int, int]] = ((640, 600), (680, 600))

    @classmethod
    def get_all(cls) -> dict[str, tuple]:
        """返回所有热区字典（用于终端打印校准）。"""
        return {
            "SUNFLOWER_POS": cls.SUNFLOWER_POS,
            "PEASHOOTER_MOUTH": cls.PEASHOOTER_MOUTH,
            "CHOMPER_FACE": cls.CHOMPER_FACE,
            "SQUASH_EYES": cls.SQUASH_EYES,
        }

    @classmethod
    def set_hotspot(cls, name: str, *args) -> bool:
        """动态设置热区坐标。

        Args:
            name: 热区名称（SUNFLOWER_POS / PEASHOOTER_MOUTH / CHOMPER_FACE / SQUASH_EYES）
            *args: 坐标参数

        Returns:
            True if successful, False otherwise
        """
        if name == "SUNFLOWER_POS" and len(args) == 4:
            cls.SUNFLOWER_POS = args
            print(f"[校准] SUNFLOWER_POS = {args}")
            return True
        elif name == "PEASHOOTER_MOUTH" and len(args) == 2:
            cls.PEASHOOTER_MOUTH = args
            print(f"[校准] PEASHOOTER_MOUTH = {args}")
            return True
        elif name == "CHOMPER_FACE" and len(args) == 4:
            cls.CHOMPER_FACE = args
            print(f"[校准] CHOMPER_FACE = {args}")
            return True
        elif name == "SQUASH_EYES" and len(args) == 2 and len(args[0]) == 2:
            cls.SQUASH_EYES = args
            print(f"[校准] SQUASH_EYES = {args}")
            return True
        print(f"[校准] 设置失败: {name} {args}")
        return False


# ── 缓动函数 ────────────────────────────────────────────────────────
def _ease_out_cubic(t: float) -> float:
    """三次缓出。"""
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out_sine(t: float) -> float:
    """正弦缓入缓出。"""
    return (1 - math.cos(math.pi * t)) / 2


# ── 粒子系统 ────────────────────────────────────────────────────────


class Projectile:
    """飞行豌豆粒子（自动销毁防泄漏）。"""

    _pool: list["Projectile"] = []

    def __init__(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        control_offset: float = 0.3,
    ) -> None:
        self.start = start
        self.end = end
        # 控制点偏移量（决定曲线弧度）
        self.cp = (
            start[0] + (end[0] - start[0]) * control_offset,
            start[1] - 200,  # 控制点向上偏移，形成抛物线
        )
        self.t: float = 0.0
        self.speed: float = 1.2  # t 增量速度
        self.alive: bool = True
        self.history: list[tuple[int, int, float]] = []  # (x, y, alpha)
        self.history_max: int = 12  # 拖尾历史点数

    @staticmethod
    def spawn(
        start: tuple[int, int],
        end: tuple[int, int],
        control_offset: float = 0.3,
    ) -> "Projectile":
        """对象池方式创建粒子。"""
        # 尝试复用
        for p in Projectile._pool:
            if not p.alive:
                p.__init__(start, end, control_offset)
                return p
        # 新建
        p = Projectile(start, end, control_offset)
        Projectile._pool.append(p)
        return p

    def update(self, dt: float) -> None:
        """更新粒子位置。"""
        if not self.alive:
            return

        # 记录历史（用于拖尾）
        pos = self._bezier(self.t)
        self.history.append((int(pos[0]), int(pos[1]), 0.6))
        if len(self.history) > self.history_max:
            self.history.pop(0)

        # 推进
        self.t += self.speed * dt
        if self.t >= 1.0:
            self.alive = False

        # 历史 alpha 衰减
        for i, (_, _, alpha) in enumerate(self.history):
            self.history[i] = (self.history[i][0], self.history[i][1], alpha * 0.85)

    def _bezier(self, t: float) -> tuple[float, float]:
        """二阶贝塞尔曲线。"""
        cx, cy = self.cp
        sx, sy = self.start
        ex, ey = self.end
        x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * ex
        y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * ey
        return (x, y)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制粒子及拖尾。"""
        if not self.alive:
            return

        # 拖尾（从旧到新绘制，alpha 递减）
        for i, (hx, hy, alpha) in enumerate(self.history):
            size = int(6 + (i / len(self.history)) * 4)  # 越新的点越大
            trail_surf = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            trail_color = (50, 200, 50, int(alpha * 180))
            pygame.draw.circle(trail_surf, trail_color, (size, size), size)
            surface.blit(trail_surf, (hx - size, hy - size))

        # 主粒子
        pos = self._bezier(self.t)
        radius = 8
        main_surf = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        main_color = (60, 220, 60, 220)
        pygame.draw.circle(main_surf, main_color, (radius + 2, radius + 2), radius)
        # 高光
        pygame.draw.circle(main_surf, (200, 255, 200, 200), (radius, radius), 4)
        surface.blit(main_surf, (int(pos[0]) - radius - 2, int(pos[1]) - radius - 2))


# ── 特效基类 ────────────────────────────────────────────────────────


class PlantEffectState(Enum):
    """植物特效状态枚举。"""
    IDLE = auto()
    ACTIVE = auto()
    COOLDOWN = auto()


class PlantEffect:
    """植物特效基类（状态机管理）。"""

    def __init__(self, name: str, anim_ms: int = _ANIM_DURATION_MS,
                 cooldown_ms: int = _COOLDOWN_DURATION_MS) -> None:
        self.name = name
        self.state: PlantEffectState = PlantEffectState.IDLE
        self.anim_ms: int = anim_ms
        self.cooldown_ms: int = cooldown_ms
        self.timer: float = 0.0  # 当前计时（秒）
        self.trigger_count: int = 0  # 触发计数
        self._last_state: PlantEffectState = PlantEffectState.IDLE

    def trigger(self) -> bool:
        """触发特效。返回 True 表示成功触发。"""
        if self.state != PlantEffectState.IDLE:
            return False
        self.state = PlantEffectState.ACTIVE
        self.timer = 0.0
        self.trigger_count += 1
        print(f"[植物特效] {self.name} 触发 #{self.trigger_count} | 持续 {self.anim_ms / 1000:.1f}s")
        return True

    def update(self, dt: float) -> None:
        """更新状态机计时。"""
        self.timer += dt * 1000  # 转为毫秒

        if self.state == PlantEffectState.ACTIVE:
            if self.timer >= self.anim_ms:
                self.state = PlantEffectState.COOLDOWN
                self.timer = 0.0

        elif self.state == PlantEffectState.COOLDOWN:
            if self.timer >= self.cooldown_ms:
                self.state = PlantEffectState.IDLE
                self.timer = 0.0

        self._last_state = self.state

    def is_active(self) -> bool:
        """是否正在播放动画。"""
        return self.state == PlantEffectState.ACTIVE

    def progress(self) -> float:
        """返回当前动画进度 [0, 1]。"""
        if self.state == PlantEffectState.ACTIVE:
            return min(self.timer / self.anim_ms, 1.0)
        return 0.0

    def cooldown_progress(self) -> float:
        """返回冷却进度 [0, 1]。"""
        if self.state == PlantEffectState.COOLDOWN:
            return min(self.timer / self.cooldown_ms, 1.0)
        return 0.0


# ── 向日葵特效 ──────────────────────────────────────────────────────


class SunflowerEffect(PlantEffect):
    """向日葵特效：径向渐变光晕呼吸。"""

    def __init__(self) -> None:
        super().__init__("Sunflower")
        self._glow_radius_base: float = 40.0
        self._glow_radius_max: float = 70.0
        self._glow_alpha_base: float = 0.4
        self._glow_alpha_max: float = 0.7

    def draw(self, surface: pygame.Surface) -> None:
        """绘制径向渐变光晕。"""
        if not self.is_active():
            return

        # 正弦脉动
        progress = self.progress()
        pulse = (math.sin(progress * math.pi * 4) + 1) / 2  # 2个完整周期
        radius = self._glow_radius_base + (self._glow_radius_max - self._glow_radius_base) * pulse
        alpha = self._glow_alpha_base + (self._glow_alpha_max - self._glow_alpha_base) * pulse

        cx, cy, _, _ = Hotspots.SUNFLOWER_POS
        center_x = cx + 40  # 热区中心
        center_y = cy + 40

        # 绘制多层径向渐变（从内到外，透明度递减）
        for i in range(4, 0, -1):
            layer_radius = radius * (i / 4)
            layer_alpha = int(alpha * 255 * (i / 4) * 0.8)
            glow_surf = pygame.Surface((int(layer_radius * 2 + 4), int(layer_radius * 2 + 4)), pygame.SRCALPHA)
            glow_color = (255, 215, 0, layer_alpha)  # 金黄色
            pygame.draw.circle(glow_surf, glow_color,
                               (int(layer_radius + 2), int(layer_radius + 2)), int(layer_radius))
            surface.blit(glow_surf, (int(center_x - layer_radius - 2), int(center_y - layer_radius - 2)))


# ── 豌豆射手特效 ────────────────────────────────────────────────────


class PeashooterEffect(PlantEffect):
    """豌豆射手特效：发射贝塞尔曲线粒子。"""

    def __init__(self) -> None:
        super().__init__("Peashooter")
        self.projectiles: list[Projectile] = []
        self._flash_timer: float = 0.0
        self._has_flashed: bool = False
        self._screen_end: tuple[int, int] = (512, 0)  # 默认屏幕顶部中点

    def trigger(self) -> bool:
        """触发时立即发射粒子。"""
        if not super().trigger():
            return False
        # 发射一颗豌豆
        mouth_x, mouth_y = Hotspots.PEASHOOTER_MOUTH
        proj = Projectile.spawn(
            start=(mouth_x, mouth_y),
            end=(self._screen_end[0], self._screen_end[1]),
            control_offset=0.4,
        )
        self.projectiles.append(proj)
        self._flash_timer = 0.0
        self._has_flashed = True
        return True

    def set_screen_end(self, x: int, y: int) -> None:
        """设置粒子终点坐标。"""
        self._screen_end = (x, y)

    def update(self, dt: float) -> None:
        """更新所有粒子。"""
        super().update(dt)

        # 更新闪光计时
        if self._has_flashed:
            self._flash_timer += dt

        # 更新粒子
        for p in self.projectiles:
            p.update(dt)

        # 清理死亡粒子
        self.projectiles = [p for p in self.projectiles if p.alive]

    def draw(self, surface: pygame.Surface) -> None:
        """绘制粒子和发射闪光。"""
        if not self.is_active():
            return

        # 发射闪光（后坐力效果）
        if self._has_flashed and self._flash_timer < 0.1:
            mouth_x, mouth_y = Hotspots.PEASHOOTER_MOUTH
            flash_radius = int(10 + self._flash_timer * 100)
            flash_alpha = int(255 * (1 - self._flash_timer * 10))
            flash_surf = pygame.Surface((flash_radius * 2 + 4, flash_radius * 2 + 4), pygame.SRCALPHA)
            flash_color = (255, 255, 200, flash_alpha)
            pygame.draw.circle(flash_surf, flash_color,
                               (flash_radius + 2, flash_radius + 2), flash_radius)
            surface.blit(flash_surf, (mouth_x - flash_radius - 2, mouth_y - flash_radius - 2))

        # 绘制所有粒子
        for p in self.projectiles:
            p.draw(surface)


# ── 大嘴花特效 ──────────────────────────────────────────────────────


class ChomperEffect(PlantEffect):
    """大嘴花特效：高频残影覆盖模拟摇头。"""

    def __init__(self) -> None:
        super().__init__("Chomper")
        self._frequency_hz: float = 2.0  # 摇头频率，可调低避免卡顿
        self._amplitude_px: float = 6.0  # 偏移幅度（像素）
        self._shake_count: int = 3  # 残影层数

    def set_frequency(self, hz: float) -> None:
        """设置摇头频率（Hz）。建议 1~3。"""
        self._frequency_hz = max(0.5, min(hz, 5.0))
        print(f"[校准] Chomper 摇头频率 = {self._frequency_hz} Hz")

    def draw(self, surface: pygame.Surface) -> None:
        """绘制高频残影条纹。"""
        if not self.is_active():
            return

        progress = self.progress()
        x, y, w, h = Hotspots.CHOMPER_FACE
        center_x = x + w // 2
        center_y = y + h // 2

        # 计算当前偏移（正弦振动）
        phase = progress * math.pi * 2 * self._frequency_hz * 2  # 2个完整周期
        offset = math.sin(phase) * self._amplitude_px

        # 绘制多层半透明残影
        for i in range(self._shake_count, 0, -1):
            layer_alpha = int(80 * (i / self._shake_count))
            stripe_surf = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)

            # 条纹颜色（紫色系）
            stripe_color = (180, 80, 200, layer_alpha)

            # 绘制横条纹
            stripe_height = 6
            stripe_gap = 10
            for sy in range(0, h, stripe_gap):
                pygame.draw.rect(
                    stripe_surf, stripe_color,
                    (2 + int(offset * i * 0.3), sy + 2, w, stripe_height)
                )

            surface.blit(stripe_surf, (center_x - w // 2 - 2, center_y - h // 2 - 2))

        # 中心叠加一条亮线（加强抖动感）
        highlight_surf = pygame.Surface((w + 4, 8), pygame.SRCALPHA)
        highlight_color = (220, 120, 255, 180)
        pygame.draw.rect(highlight_surf, highlight_color, (2 + int(offset), 0, w, 8))
        surface.blit(highlight_surf, (center_x - w // 2 - 2, center_y - 4))


# ── 窝瓜特效 ────────────────────────────────────────────────────────


class SquashEffect(PlantEffect):
    """窝瓜特效：瞳孔追踪鼠标。"""

    def __init__(self) -> None:
        super().__init__("Squash")
        self.mouse_pos: tuple[int, int] = (0, 0)
        self._eye_radius: float = 9.0   # 巩膜半径
        self._pupil_radius: float = 4.0  # 瞳孔半径
        self._max_offset: float = 5.0    # 瞳孔最大偏移
        self._current_offset: tuple[float, float] = (0.0, 0.0)
        self._target_offset: tuple[float, float] = (0.0, 0.0)

    def set_mouse(self, pos: tuple[int, int]) -> None:
        """设置当前鼠标坐标。"""
        self.mouse_pos = pos

    def _calculate_offset(self, eye_center: tuple[int, int]) -> tuple[float, float]:
        """根据鼠标位置计算瞳孔偏移。"""
        dx = self.mouse_pos[0] - eye_center[0]
        dy = self.mouse_pos[1] - eye_center[1]
        distance = math.sqrt(dx * dx + dy * dy)
        if distance < 1:
            return (0.0, 0.0)
        # 归一化并限制最大偏移
        scale = min(distance, self._max_offset) / distance
        return (dx * scale, dy * scale)

    def update(self, dt: float) -> None:
        """更新瞳孔位置（缓动插值）。"""
        super().update(dt)

        # 实时计算目标偏移
        left_eye, right_eye = Hotspots.SQUASH_EYES
        self._target_offset = self._calculate_offset(left_eye)

        # 缓动插值到目标（平滑追踪）
        easing = 1.0 - (1.0 - _ease_out_cubic(min(dt * 8, 1.0)))
        cx, cy = self._current_offset
        tx, ty = self._target_offset
        self._current_offset = (
            cx + (tx - cx) * easing,
            cy + (ty - cy) * easing,
        )

    def draw(self, surface: pygame.Surface) -> None:
        """绘制眼球和追踪瞳孔。"""
        left_eye, right_eye = Hotspots.SQUASH_EYES
        ox, oy = self._current_offset

        for eye_center in [left_eye, right_eye]:
            ex, ey = eye_center

            # 绘制巩膜（白色底）
            sclera_surf = pygame.Surface((int(self._eye_radius * 2 + 2), int(self._eye_radius * 2 + 2)), pygame.SRCALPHA)
            pygame.draw.circle(sclera_surf, (240, 230, 210, 255),
                               (int(self._eye_radius + 1), int(self._eye_radius + 1)), int(self._eye_radius))
            surface.blit(sclera_surf, (int(ex - self._eye_radius - 1), int(ey - self._eye_radius - 1)))

            # 绘制瞳孔（黑色，跟随偏移）
            pupil_x = ex + ox
            pupil_y = ey + oy
            pupil_surf = pygame.Surface((int(self._pupil_radius * 2 + 2), int(self._pupil_radius * 2 + 2)), pygame.SRCALPHA)
            pygame.draw.circle(pupil_surf, (20, 20, 20, 255),
                               (int(self._pupil_radius + 1), int(self._pupil_radius + 1)), int(self._pupil_radius))
            surface.blit(pupil_surf, (int(pupil_x - self._pupil_radius - 1), int(pupil_y - self._pupil_radius - 1)))

            # 高光点
            highlight_surf = pygame.Surface((4, 4), pygame.SRCALPHA)
            pygame.draw.circle(highlight_surf, (255, 255, 255, 200), (2, 2), 2)
            surface.blit(highlight_surf, (int(pupil_x - 4), int(pupil_y - 4)))


# ── 主管理器 ────────────────────────────────────────────────────────


class MenuEffects:
    """菜单植物交互特效管理器。"""

    def __init__(self, screen_w: int, screen_h: int) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h

        # 初始化所有特效
        self.sunflower = SunflowerEffect()
        self.peashooter = PeashooterEffect()
        self.chomper = ChomperEffect()
        self.squash = SquashEffect()

        # 设置豌豆终点为屏幕顶部中点
        self.peashooter.set_screen_end(screen_w // 2, 0)

        # 打印初始坐标（方便校准）
        self._print_hotspots()

    def _print_hotspots(self) -> None:
        """启动时打印热区坐标。"""
        print(f"[校准] 当前热区坐标: {Hotspots.get_all()}")

    def set_hotspot(self, name: str, *args) -> None:
        """动态设置热区坐标（供外部调用微调）。"""
        Hotspots.set_hotspot(name, *args)

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        button_rects: dict[str, pygame.Rect],
    ) -> None:
        """更新所有特效。

        Args:
            dt: 帧时间（秒）
            mouse_pos: 当前鼠标坐标
            button_rects: 按钮区域字典 {"pve": Rect, "achievement": Rect, "pvp": Rect, "squash": Rect}
        """
        # 更新窝瓜鼠标追踪
        self.squash.set_mouse(mouse_pos)

        # 检测悬停并触发对应特效
        for btn_key, rect in button_rects.items():
            if rect.collidepoint(mouse_pos):
                if btn_key == "pve":
                    self.peashooter.trigger()
                elif btn_key == "achievement":
                    self.sunflower.trigger()
                elif btn_key == "pvp":
                    self.chomper.trigger()
                elif btn_key == "squash":
                    self.squash.trigger()
                break  # 一次只触发一个

        # 更新所有特效
        self.sunflower.update(dt)
        self.peashooter.update(dt)
        self.chomper.update(dt)
        self.squash.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        """按层级绘制所有活跃特效。

        绘制顺序：窝瓜(底部) → 大嘴花 → 向日葵 → 豌豆射手(顶部)
        """
        # 窝瓜 - 始终追踪鼠标
        self.squash.draw(surface)

        # 大嘴花 - 残影抖动
        self.chomper.draw(surface)

        # 向日葵 - 光晕呼吸
        self.sunflower.draw(surface)

        # 豌豆射手 - 粒子飞射
        self.peashooter.draw(surface)
