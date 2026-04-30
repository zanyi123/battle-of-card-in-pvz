from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import pygame

from ui.asset_manager import AssetManager
from ui.floating_text import FloatingTextManager
from utils.path_utils import get_resource_path


# ── 阵营颜色映射（RGB）────────────────────────────────────────────
FACTION_COLORS: dict[str, tuple[int, int, int]] = {
    "法": (138, 43, 226),   # 紫色
    "射": (30, 144, 255),   # 道奇蓝
    "坦": (160, 82, 45),    # 棕色
    "辅": (255, 215, 0),   # 金色
}


def _create_star_surface() -> pygame.Surface:
    """创建白色四角星 Surface（10x10），用于粒子渲染。"""
    surf = pygame.Surface((10, 10), pygame.SRCALPHA)
    # 四角星顶点
    points = [(5, 0), (7, 3), (10, 5), (7, 7), (5, 10), (3, 7), (0, 5), (3, 3)]
    pygame.draw.polygon(surf, (255, 255, 255, 255), points)
    return surf


# 预生成四角星底图（全局复用，避免每帧创建 Surface）
STAR_SURF: pygame.Surface = _create_star_surface()


class EdgeParticle:
    """边缘四角星粒子，严格从卡牌边缘生成并向外扩散。"""

    __slots__ = ("x", "y", "color", "life", "decay", "vx", "vy", "_origin_x", "_origin_y", "max_dist")

    def __init__(
        self,
        card_rect: pygame.Rect,
        faction_color: tuple[int, int, int],
    ) -> None:
        # 计算卡牌中心
        cx, cy = card_rect.centerx, card_rect.centery

        # 严格从四条边缘随机选点生成
        edge = random.choice(["top", "bottom", "left", "right"])
        if edge == "top":
            self.x = random.randint(card_rect.left, card_rect.right)
            self.y = float(card_rect.top)
        elif edge == "bottom":
            self.x = random.randint(card_rect.left, card_rect.right)
            self.y = float(card_rect.bottom)
        elif edge == "left":
            self.x = float(card_rect.left)
            self.y = random.randint(card_rect.top, card_rect.bottom)
        else:  # right
            self.x = float(card_rect.right)
            self.y = random.randint(card_rect.top, card_rect.bottom)

        # 速度向量严格朝外（背离中心）
        dx = self.x - cx
        dy = self.y - cy
        dist = math.hypot(dx, dy) or 1.0
        speed = random.uniform(0.6, 1.2)  # 低速柔和扩散
        self.vx = (dx / dist) * speed
        self.vy = (dy / dist) * speed

        # 记录初始位置（用于距离计算）
        self._origin_x = cx
        self._origin_y = cy

        self.color = faction_color
        self.life = 1.0
        self.decay = 0.015  # 缓慢消失
        self.max_dist = 22  # 最大扩散半径，确保不碰邻卡

    def update(self) -> None:
        """更新粒子位置和生命周期。"""
        self.x += self.vx
        self.y += self.vy
        self.life -= self.decay

        # 超出安全距离加速消散，防止干扰
        traveled = math.hypot(self.x - self._origin_x, self.y - self._origin_y)
        if traveled > self.max_dist:
            self.life -= 0.05

    def draw(self, screen: pygame.Surface) -> None:
        """将粒子绘制到屏幕，使用阵营色着色。"""
        if self.life <= 0:
            return
        # 动态着色：保留四角星高光，叠加阵营色
        alpha = int(self.life * 180)
        tinted = STAR_SURF.copy()
        tinted.fill((*self.color, alpha), special_flags=pygame.BLEND_RGBA_MULT)
        screen.blit(tinted, (int(self.x - 5), int(self.y - 5)))


class CardRenderer:
    CARD_W = 80
    CARD_H = 120
    HOVER_OFFSET_Y = 15
    TOOLTIP_W = 200
    TOOLTIP_MIN_H = 100
    TOOLTIP_PAD = 10
    TOOLTIP_GAP = 12
    EFFECT_TEXT_MAP: dict[str, str] = {
        "burn": "灼烧：对目标造成持续伤害",
        "heal_all": "治愈：回复全体友方生命",
        "shield": "护盾：本回合降低受到伤害",
    }
    # 需要从显示名称中去除的阵营后缀
    _FACTION_SUFFIXES: tuple[str, ...] = ("fa", "fu", "sh", "tk")

    def __init__(self, asset_manager: AssetManager, font_getter: callable) -> None:
        self.asset_manager = asset_manager
        self.font_getter = font_getter

    def draw_card(
        self,
        surface: pygame.Surface,
        card: Any,
        x: int,
        y: int,
        is_hover: bool = False,
        scale: float = 1.0,
    ) -> pygame.Rect:
        """绘制卡牌正面，scale < 1 时缩小显示（用于历史出牌）。

        绘制层级（自下而上）：
        ① 阵营背景图  ② 植物插图（60×80 安全区居中）  ③ 边框
        ④ 左上精力底图 + 白色数字 / 右上攻击底图 + 白色数字
        ⑤ 左下限制符标志（仅 limit_flag=True/1）
        ⑥ 底部名称条（cy + 100 处，高 20px）
        """
        card_w = int(self.CARD_W * scale)
        card_h = int(self.CARD_H * scale)
        draw_y = y - int(self.HOVER_OFFSET_Y * scale) if is_hover else y
        card_rect = pygame.Rect(x, draw_y, card_w, card_h)

        # ── ① 阵营背景图（最底层）───────────────────────────────────
        faction_key = self.asset_manager._normalize_faction_key(
            getattr(card, "faction", getattr(card, "type", ""))
        )
        bg_surface = self.asset_manager._load_faction_bg(faction_key)
        if bg_surface is not None:
            bg = bg_surface if scale == 1.0 else pygame.transform.smoothscale(bg_surface, (card_w, card_h))
            surface.blit(bg, card_rect.topleft)
        else:
            # 阵营背景缺失时用纯色兜底
            fallback_color = self.asset_manager._FACTION_COLORS.get(faction_key, (90, 90, 90))
            pygame.draw.rect(surface, fallback_color, card_rect, border_radius=6)

        # ── ② 植物插图（等比缩放至 60×80 安全区，居中放置）───────────
        safe_w = int(60 * scale)
        safe_h = int(80 * scale)

        plant_img = self.asset_manager._get_plant_image(
            getattr(card, "image_file", ""), card.id,
            getattr(card, "faction", getattr(card, "type", "")),
        )
        if plant_img is not None:
            # 等比缩放：保持宽高比，适应安全区
            img_w, img_h = plant_img.get_size()
            ratio = min(safe_w / max(img_w, 1), safe_h / max(img_h, 1))
            scaled_w = max(1, int(img_w * ratio))
            scaled_h = max(1, int(img_h * ratio))
            plant_scaled = pygame.transform.smoothscale(plant_img, (scaled_w, scaled_h))
            # 居中偏移：安全区中心 - 缩放后中心
            img_safe_x = card_rect.x + (card_w - scaled_w) // 2
            img_safe_y = card_rect.y + int(20 * scale) + (safe_h - scaled_h) // 2
            surface.blit(plant_scaled, (img_safe_x, img_safe_y))

        # ── 边框 ────────────────────────────────────────────────────
        border_color = (240, 220, 80) if is_hover else (150, 150, 150)
        border_w = 3 if is_hover else 1
        pygame.draw.rect(surface, border_color, card_rect, width=border_w, border_radius=6)

        # ── ③ 左上角精力底图 + 下方亮黄数字 ──────────────────────
        badge_size = (max(12, int(22 * scale)), max(12, int(22 * scale)))
        cost_x = card_rect.x + int(4 * scale)
        cost_y = card_rect.y + int(4 * scale)
        cost_badge = self.asset_manager.get_stat_badge("energy", badge_size)
        surface.blit(cost_badge, (cost_x, cost_y))
        # 费用数字：图标正下方居中，亮黄色
        font_size_stat = max(9, int(13 * scale))
        cost_text = self.font_getter(font_size_stat).render(
            str(int(getattr(card, "cost", 0))), True, (255, 220, 0),
        )
        cost_text_x = cost_x + (badge_size[0] - cost_text.get_width()) // 2
        cost_text_y = cost_y + badge_size[1] + int(2 * scale)
        surface.blit(cost_text, (cost_text_x, cost_text_y))

        # ── ④ 右上角攻击底图 + 下方鲜红数字 ──────────────────────
        atk_badge_size = badge_size
        atk_x = card_rect.x + card_w - int(4 * scale) - atk_badge_size[0]
        atk_y = card_rect.y + int(4 * scale)
        atk_badge = self.asset_manager.get_stat_badge("atk", atk_badge_size)
        surface.blit(atk_badge, (atk_x, atk_y))
        # 攻击数字：图标正下方居中，鲜红色
        atk_text = self.font_getter(font_size_stat).render(
            str(int(getattr(card, "atk", 0))), True, (255, 50, 50),
        )
        atk_text_x = atk_x + (atk_badge_size[0] - atk_text.get_width()) // 2
        atk_text_y = atk_y + atk_badge_size[1] + int(2 * scale)
        surface.blit(atk_text, (atk_text_x, atk_text_y))

        # ── ④⑤ 限制符标志（左下角，仅 limit_flag=True/1 时显示）─────
        limit_flag = getattr(card, "limit_flag", False)
        if limit_flag is True or limit_flag == 1:
            limit_badge_size = (max(10, int(18 * scale)), max(10, int(18 * scale)))
            limit_x = card_rect.x + int(4 * scale)
            limit_y = card_rect.y + card_h - int(4 * scale) - limit_badge_size[1]
            limit_badge = self.asset_manager.get_stat_badge("limit", limit_badge_size)
            surface.blit(limit_badge, (limit_x, limit_y))

        # ── ⑤ 底部名称条（固定 cy + 100 处，高 20px）──────────────
        name_bar_h = max(14, int(20 * scale))
        name_bar_y = card_rect.y + int(100 * scale)
        # 确保名称条不超出卡牌底部
        if name_bar_y + name_bar_h > card_rect.bottom:
            name_bar_y = card_rect.bottom - name_bar_h
        name_bar = pygame.Surface((card_w, name_bar_h), pygame.SRCALPHA)
        name_bar.fill((0, 0, 0, 160))
        surface.blit(name_bar, (card_rect.x, name_bar_y))

        font_size = max(10, int(14 * scale))
        name_font = self.font_getter(font_size)
        raw_name = str(getattr(card, "name", "") or "")
        display_name = self._clean_card_name(raw_name)
        max_chars = 4 if scale >= 0.9 else 3
        short_name = display_name if len(display_name) <= max_chars else f"{display_name[:max_chars]}.."
        name_text = name_font.render(short_name, True, (255, 255, 255))
        name_rect = name_text.get_rect(center=(card_rect.centerx, name_bar_y + name_bar_h // 2))
        surface.blit(name_text, name_rect)

        return card_rect

    def draw_card_back(
        self,
        surface: pygame.Surface,
        x: int,
        y: int,
        card_w: int | None = None,
        card_h: int | None = None,
    ) -> pygame.Rect:
        """绘制卡牌背面（用于对手手牌）。"""
        w = card_w if card_w is not None else self.CARD_W
        h = card_h if card_h is not None else self.CARD_H
        raw = self.asset_manager.get_card_back()
        if (w, h) != (self.CARD_W, self.CARD_H):
            img = pygame.transform.smoothscale(raw, (w, h))
        else:
            img = raw
        rect = pygame.Rect(x, y, w, h)
        surface.blit(img, rect.topleft)
        pygame.draw.rect(surface, (110, 120, 140), rect, width=1, border_radius=6)
        return rect

    def draw_card_tooltip(self, surface: pygame.Surface, card: Any, mouse_x: int, mouse_y: int) -> pygame.Rect:
        title_font = self.font_getter(20, bold=True)
        meta_font = self.font_getter(14)
        body_font = self.font_getter(15)

        desc = str(getattr(card, "description", "") or "")
        effect_id = str(getattr(card, "effect_id", "") or "")
        faction_name = self._faction_name(card)
        raw_type = str(getattr(card, "type", "") or "")
        card_type = "辅卡" if raw_type == "辅" else "主卡"
        cost = int(getattr(card, "cost", 0))
        atk = int(getattr(card, "atk", 0))
        meta_text = f"{faction_name} | {card_type} | 费用:{cost} 攻击:{atk}"

        body_lines = self._wrap_text(desc or "暂无背景介绍", body_font, self.TOOLTIP_W - self.TOOLTIP_PAD * 2)
        effect_line = ""
        if effect_id:
            effect_line = self.EFFECT_TEXT_MAP.get(effect_id, f"技能ID: {effect_id}")

        line_h_title = title_font.get_height() + 2
        line_h_meta = meta_font.get_height() + 2
        line_h_body = body_font.get_height() + 2
        h = self.TOOLTIP_PAD * 2 + line_h_title + line_h_meta + len(body_lines) * line_h_body
        if effect_line:
            h += line_h_body + 4
        h = max(self.TOOLTIP_MIN_H, h)

        x = mouse_x + self.TOOLTIP_GAP
        y = mouse_y
        if x + self.TOOLTIP_W > surface.get_width():
            x = max(0, mouse_x - self.TOOLTIP_W - self.TOOLTIP_GAP)
        if y + h > surface.get_height():
            y = max(0, surface.get_height() - h - 4)

        tip_rect = pygame.Rect(x, y, self.TOOLTIP_W, h)
        tip_bg = pygame.Surface((tip_rect.w, tip_rect.h), pygame.SRCALPHA)
        tip_bg.fill((0, 0, 0, 210))
        surface.blit(tip_bg, tip_rect.topleft)
        pygame.draw.rect(surface, (190, 190, 190), tip_rect, width=1, border_radius=8)

        title = self._clean_card_name(str(getattr(card, "name", "Unknown")))
        title_surf = title_font.render(title, True, (255, 255, 255))
        surface.blit(title_surf, (x + self.TOOLTIP_PAD, y + self.TOOLTIP_PAD))

        cursor_y = y + self.TOOLTIP_PAD + line_h_title
        meta_surf = meta_font.render(meta_text, True, (210, 210, 210))
        surface.blit(meta_surf, (x + self.TOOLTIP_PAD, cursor_y))
        cursor_y += line_h_meta

        for line in body_lines:
            line_surf = body_font.render(line, True, (230, 230, 230))
            surface.blit(line_surf, (x + self.TOOLTIP_PAD, cursor_y))
            cursor_y += line_h_body

        if effect_line:
            cursor_y += 4
            effect_surf = body_font.render(effect_line, True, (245, 220, 90))
            surface.blit(effect_surf, (x + self.TOOLTIP_PAD, cursor_y))

        return tip_rect

    def _draw_stat_circle(
        self,
        surface: pygame.Surface,
        center: tuple[int, int],
        value: int,
        bg: tuple[int, int, int],
        radius: int = 11,
    ) -> None:
        pygame.draw.circle(surface, bg, center, radius)
        font_size = max(9, int(radius * 1.2))
        text = self.font_getter(font_size).render(str(value), True, (255, 255, 255))
        text_rect = text.get_rect(center=center)
        surface.blit(text, text_rect)

    @staticmethod
    def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        if not text:
            return [""]
        lines: list[str] = []
        current = ""
        for ch in text:
            trial = current + ch
            if font.size(trial)[0] <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = ch
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _faction_name(card: Any) -> str:
        faction = getattr(card, "faction", getattr(card, "type", ""))
        if hasattr(faction, "name"):
            return str(faction.name)
        return str(faction or "未知")

    @staticmethod
    def _clean_card_name(raw_name: str) -> str:
        """清洗卡牌名称：去除 ASCII 阵营后缀（fa/fu/sh/tk）并清理多余空格。

        仅在名称包含 ASCII 字母时才生效（纯中文名不受影响）。
        """
        cleaned = raw_name.strip()
        # 仅当名称含 ASCII 字母时执行后缀清洗
        if any(c.isascii() and c.isalpha() for c in cleaned):
            cleaned = cleaned.replace("fa", "").replace("fu", "").replace("s", "").replace("t", "")
            cleaned = cleaned.strip()
        return cleaned or raw_name


class Renderer:
    # ── 资源路径 ─────────────────────────────────────────────────
    _IMG_ROOT = get_resource_path("assets/images")
    _BG_BATTLE = "bg_battle_table.jpg"

    def __init__(self, screen: pygame.Surface, screen_size: tuple[int, int] = (1024, 768)) -> None:
        self.screen = screen
        self.screen_w, self.screen_h = screen_size
        self.asset_manager = AssetManager()
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self._cjk_font_path = get_resource_path("assets/fonts/SourceHanSansSC-Regular.otf")
        self._fallback_font_path = get_resource_path("assets/fonts/simhei.ttf")
        self.card_renderer = CardRenderer(self.asset_manager, self.get_text_font)
        self.font = self.get_text_font(20)
        self.small_font = self.get_text_font(16)
        self.zones = self._build_zones()
        # ── 飘字管理器 ────────────────────────────────────────
        self.floating_text_manager: FloatingTextManager = FloatingTextManager(self.get_text_font)
        # ── Buff 图标缓存 ─────────────────────────────────────
        self._buff_images: dict[str, pygame.Surface] = {}
        self._load_buff_images()
        # ── 背景图 ─────────────────────────────────────────────
        self._bg: pygame.Surface | None = self._load_bg()
        # ── 悬停粒子系统 ───────────────────────────────────────
        self._particles: list[EdgeParticle] = []
        # ── 认输按钮区域（由 _draw_surrender_button 每帧更新）────
        self.surrender_btn_rect: pygame.Rect | None = None
        # ── 游戏结束按钮区域（无力回天"好吧"按钮）──────────────
        self.game_over_btn_rect: pygame.Rect | None = None
        # ── 胜利结算按钮区域（"简简单单啊~"按钮）────────────────
        self.victory_btn_rect: pygame.Rect | None = None
        # ── 设置面板状态 ─────────────────────────────────────────
        self.settings_active: bool = False
        self.settings_back_btn: pygame.Rect | None = None
        self._slider_dragging: str | None = None  # 当前拖拽中的滑块 key
        # ── 暂停按钮/面板状态 ──────────────────────────────────
        self.pause_btn_rect: pygame.Rect | None = None
        self.pause_active: bool = False
        self.pause_back_btn: pygame.Rect | None = None
        self._pause_card_seed: int | None = None  # 暂停面板随机卡牌种子
        self._pause_card_surf: pygame.Surface | None = None  # 缓存的卡牌缩放图

    def _load_bg(self) -> pygame.Surface | None:
        """加载游戏背景图 bg_battle_table.jpg。"""
        bg_path = self._IMG_ROOT / self._BG_BATTLE
        if bg_path.exists():
            try:
                surf = pygame.image.load(str(bg_path)).convert()
                return surf
            except pygame.error:
                return None
        return None

    def get_hand_card_hit(
        self, pos: tuple[int, int], hand_cards: list[Any],
    ) -> tuple[int, pygame.Rect] | None:
        """检测鼠标是否点击了 P1 手牌区的某张卡牌。

        布局与 _draw_hand_cards 保持一致：y=550, start_x=280, step=90。

        Args:
            pos: 鼠标坐标 (x, y)。
            hand_cards: P1 手牌列表。

        Returns:
            (index, rect) 命中的卡牌索引和区域，未命中返回 None。
        """
        hand_y = 550
        start_x = 280
        for index in range(len(hand_cards)):
            x = start_x + index * 90
            rect = pygame.Rect(x, hand_y, CardRenderer.CARD_W, CardRenderer.CARD_H)
            if rect.collidepoint(pos):
                return (index, rect)
        return None

    def get_text_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        if not pygame.font.get_init():
            pygame.font.init()
        key = (max(8, int(size)), bool(bold))
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached

        if self._cjk_font_path.exists():
            try:
                font = pygame.font.Font(str(self._cjk_font_path), key[0])
            except Exception:
                font = pygame.font.Font(str(self._fallback_font_path) if self._fallback_font_path.exists() else None, key[0])
        elif self._fallback_font_path.exists():
            font = pygame.font.Font(str(self._fallback_font_path), key[0])
        else:
            try:
                font = pygame.font.SysFont("simhei", key[0])
            except Exception:
                font = pygame.font.Font(None, key[0])
        font.set_bold(key[1])
        self._font_cache[key] = font
        return font

    def draw(self, state: dict[str, Any], logs: list[dict[str, Any]]) -> None:
        # 背景图
        if self._bg is not None:
            bg_scaled = pygame.transform.smoothscale(self._bg, (self.screen_w, self.screen_h))
            self.screen.blit(bg_scaled, (0, 0))
            # 半透明暗色蒙版，让UI元素更清晰
            mask = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
            mask.fill((0, 0, 0, 100))
            self.screen.blit(mask, (0, 0))
        else:
            self.screen.fill((28, 36, 46))
        self._draw_zones(state)
        # ── 悬停粒子层（在卡牌内容层之下，不遮挡视图）───────────
        self._update_and_draw_particles()
        self._draw_hand_cards(state)
        self._draw_deck_status(state)
        self._draw_battlefield_placeholders(state)
        self._draw_bars_and_stats(state)
        self._draw_opponent_hand(state)
        self._draw_timer(state)
        self._draw_replenish_selector(state)
        self._draw_last_logs(logs)
        self._draw_phase_hint(state)
        self._draw_game_over(state)
        # ── 飘字渲染（最顶层）───────────────────────────────────
        self.floating_text_manager.render(self.screen)
        # ── 补救回合专属渲染（最最顶层）────────────────────────
        self._draw_remedy_overlay(state)
        # ── 补牌动画渲染（最最最顶层）──────────────────────────
        self._draw_draw_animation(state)
        # ── 认输按钮（对战/补救阶段显示，最顶层）──────────────
        self._draw_surrender_button(state)
        # ── 暂停按钮（对战阶段显示，认输正下方）────────────────
        self._draw_pause_button(state)
        # ── 战报播报（最最最顶层，不阻塞游戏循环）──────────────
        self._draw_toasts(state)

    def draw_card_tooltip(self, surface: pygame.Surface, card: Any, mouse_x: int, mouse_y: int) -> pygame.Rect:
        return self.card_renderer.draw_card_tooltip(surface, card, mouse_x, mouse_y)

    def _build_zones(self) -> dict[str, pygame.Rect]:
        return {
            "opponent": pygame.Rect(60, 20, self.screen_w - 120, 170),
            "battlefield": pygame.Rect(80, 210, self.screen_w - 220, 300),
            "deck": pygame.Rect(self.screen_w - 180, 270, 120, 220),
            "hand": pygame.Rect(60, self.screen_h - 190, self.screen_w - 120, 160),
        }

    def _load_buff_images(self) -> None:
        """预加载 buff 图标。"""
        buffs_dir = get_resource_path("assets/images/buffs")
        buff_paths = {
            "shield": buffs_dir / "buff_shield.jpg",
            "heal_over_time": buffs_dir / "buff_restore HP.jpg",
        }
        for key, path in buff_paths.items():
            if path.exists():
                surf = pygame.image.load(str(path)).convert_alpha()
                surf = pygame.transform.smoothscale(surf, (40, 40))
                self._buff_images[key] = surf

    def _draw_zones(self, state: dict[str, Any]) -> None:
        hovered = state.get("ui", {}).get("hovered_zone", "")
        zone_colors = {
            "opponent": (100, 120, 130),
            "battlefield": (90, 110, 120),
            "deck": (100, 110, 150),
            "hand": (100, 120, 130),
        }

        for name, rect in self.zones.items():
            color = zone_colors[name]
            if hovered == name:
                color = (180, 160, 70)
            pygame.draw.rect(self.screen, color, rect, width=2, border_radius=10)
            label = self.font.render(name.upper(), True, (220, 220, 220))
            self.screen.blit(label, (rect.x + 8, rect.y + 8))

    def _draw_hand_cards(self, state: dict[str, Any]) -> None:
        y = 550
        start_x = 280
        mouse_pos = pygame.mouse.get_pos()
        p1_cards = state.get("hands", {}).get("P1", [])

        # 统计当前悬停的卡牌数量，每帧每张卡最多生成 1 个粒子
        hover_count = 0
        max_per_frame = 1  # 每帧每张悬停卡最多生成 1 个粒子

        for index, card in enumerate(p1_cards):
            x = start_x + index * 90
            hit_rect = pygame.Rect(x, y, CardRenderer.CARD_W, CardRenderer.CARD_H)
            is_hover = hit_rect.collidepoint(mouse_pos)

            # ── 悬停时从边缘生成粒子（限速防堆积）───────────────
            if is_hover and hover_count < max_per_frame:
                faction_raw = str(getattr(card, "faction", ""))
                faction_key = self.asset_manager._normalize_faction_key(faction_raw)
                faction_color = FACTION_COLORS.get(faction_key, (255, 255, 255))
                # 从卡牌边缘生成粒子（严格朝外扩散）
                self._particles.append(EdgeParticle(hit_rect, faction_color))
                hover_count += 1

            self.card_renderer.draw_card(self.screen, card, x, y, is_hover=is_hover)

    # ── Battlefield：包含历史出牌 + 当前回合出牌槽 ─────────────────

    def _draw_battlefield_placeholders(self, state: dict[str, Any]) -> None:
        """绘制 battlefield：历史出牌 + 当前回合出牌槽。"""
        field = self.zones["battlefield"]

        # 当前回合出牌槽位（P1/P2 PLAY SLOT）
        p1_slot = pygame.Rect(field.x + 40, field.y + 170, 120, 90)
        p2_slot = pygame.Rect(field.x + 40, field.y + 40, 120, 90)
        pygame.draw.rect(self.screen, (120, 140, 100), p1_slot, width=2, border_radius=8)
        pygame.draw.rect(self.screen, (140, 110, 100), p2_slot, width=2, border_radius=8)
        p1_txt = self.small_font.render("P1 PLAY SLOT", True, (210, 220, 210))
        p2_txt = self.small_font.render("P2 PLAY SLOT", True, (220, 210, 210))
        self.screen.blit(p1_txt, (p1_slot.x + 10, p1_slot.y + 34))
        self.screen.blit(p2_txt, (p2_slot.x + 10, p2_slot.y + 34))

        # 绘制当前回合已出牌
        # P1：PLAY_P1 阶段显示 pending_play（预出牌区），其他阶段显示 played_cards
        from core.state_machine import TurnPhase
        current_phase = state.get("phase")
        phase_is_play_p1 = (current_phase is TurnPhase.PLAY_P1 or
                            (hasattr(current_phase, "name") and current_phase.name == "PLAY_P1"))
        if phase_is_play_p1:
            p1_display = state.get("pending_play", {}).get("P1", [])
        else:
            played = state.get("played_cards", {})
            p1_display = played.get("P1", [])
        played = state.get("played_cards", {})
        self._draw_played_cards_in_slot(p1_display, p1_slot)
        self._draw_played_cards_in_slot(played.get("P2", []), p2_slot)

        # 绘制历史出牌
        self._draw_history_cards(state, field)

    def _draw_played_cards_in_slot(self, cards: list[Any], slot: pygame.Rect) -> None:
        """在槽位内堆叠显示已出的牌（最多 3 张，略微偏移）。"""
        if not cards:
            return
        # 在 slot 内水平排列，最多显示 3 张
        show = cards[:3]
        step = min(slot.width // max(len(show), 1), CardRenderer.CARD_W)
        card_h = min(slot.height, CardRenderer.CARD_H)
        card_w = int(card_h * CardRenderer.CARD_W / CardRenderer.CARD_H)
        scale = card_h / CardRenderer.CARD_H
        start_x = slot.x + (slot.width - card_w * len(show)) // 2
        for i, card in enumerate(show):
            self.card_renderer.draw_card(
                self.screen, card,
                start_x + i * (card_w + 2),
                slot.y + (slot.height - card_h) // 2,
                scale=scale,
            )

    def _draw_history_cards(self, state: dict[str, Any], field: pygame.Rect) -> None:
        """绘制前两回合的历史出牌。

        布局：
          - 第 n-2 回合（最旧）：缩略图 60×90，位于 battlefield 最左侧
          - 第 n-1 回合（较近）：缩略图 80×120（标准），位于 battlefield 右侧
        每行上方显示小标题（"第n-2回合" / "上回合"）。
        """
        history: list[dict[str, list[Any]]] = state.get("played_cards_history", [])
        if not history:
            return

        label_font = self.get_text_font(12)

        # 历史槽位定义：[(距 field.right 的偏移, 卡片宽, 卡片高, 标签)]
        # n-1（最近）：在 battlefield 右侧区域（靠近 P2/P1 SLOT 右边）
        # n-2（较旧）：在 n-1 左侧
        history_slots = [
            # (offset_right_from_field_right, card_w, card_h, label)
            (240, 60, 90, "前两回合"),   # 最旧 index 0
            (150, 80, 120, "上回合"),    # 较近 index 1
        ]

        for hist_idx, entry in enumerate(history):
            slot_def = history_slots[hist_idx]
            offset_r, card_w, card_h, label = slot_def
            scale = card_h / CardRenderer.CARD_H

            # P1 历史（下半区）
            p1_hist = entry.get("P1", [])
            # P2 历史（上半区）
            p2_hist = entry.get("P2", [])

            # 计算 x 基准（从 field 右边向左偏移）
            base_x = field.right - offset_r

            # 绘制标签
            lbl_surf = label_font.render(label, True, (180, 180, 180))
            self.screen.blit(lbl_surf, (base_x, field.y + 2))

            # P2 历史出牌行（field 上半区 y + 15）
            p2_row_y = field.y + 15
            self._draw_history_row(p2_hist, base_x, p2_row_y, card_w, card_h, scale)

            # P1 历史出牌行（field 下半区）
            p1_row_y = field.y + field.height // 2 + 10
            self._draw_history_row(p1_hist, base_x, p1_row_y, card_w, card_h, scale)

    def _draw_history_row(
        self,
        cards: list[Any],
        base_x: int,
        base_y: int,
        card_w: int,
        card_h: int,
        scale: float,
    ) -> None:
        """在 (base_x, base_y) 处水平排列绘制一组历史卡牌（最多显示 2 张）。"""
        show = cards[:2]
        for i, card in enumerate(show):
            x = base_x + i * (card_w + 3)
            # 绘制半透明蒙版标记为"已结算"
            ghost = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
            ghost.fill((0, 0, 0, 90))  # 半透明黑色遮罩
            self.card_renderer.draw_card(self.screen, card, x, base_y, scale=scale)
            self.screen.blit(ghost, (x, base_y))

    # ── 对手手牌背面 ───────────────────────────────────────────────

    def _draw_opponent_hand(self, state: dict[str, Any]) -> None:
        """在 opponent 区域下方显示 P2 手牌背面 + 张数文本。"""
        p2_hand = state.get("hands", {}).get("P2", [])
        count = len(p2_hand)
        if count == 0:
            return

        opp_zone = self.zones["opponent"]
        # 卡牌背面尺寸（比正常略小）
        back_w, back_h = 46, 68
        gap = 6
        total_w = count * back_w + (count - 1) * gap
        # 水平居中放置在 opponent 区域内，垂直居底留少量边距
        start_x = opp_zone.centerx - total_w // 2
        cards_y = opp_zone.bottom - back_h - 8

        # 限制最多显示 7 张背面（超出则只显示数字）
        show_count = min(count, 7)
        for i in range(show_count):
            x = start_x + i * (back_w + gap)
            self.card_renderer.draw_card_back(self.screen, x, cards_y, back_w, back_h)

        # 在卡牌左上方显示张数
        label_font = self.get_text_font(14)
        label = f"手牌: {count}张"
        lbl_surf = label_font.render(label, True, (210, 220, 230))
        self.screen.blit(lbl_surf, (opp_zone.x + 8, cards_y - 20))

    # ── 其余原有绘制方法 ──────────────────────────────────────────

    def _draw_deck_status(self, state: dict[str, Any]) -> None:
        deck_rect = self.zones["deck"]
        remaining = int(state.get("deck_size", 0))
        icon_rect = pygame.Rect(deck_rect.x + 14, deck_rect.y + 14, deck_rect.width - 28, 64)

        # 检查是否悬停（用于高亮）
        is_hovered = state.get("ui", {}).get("deck_hovered", False)
        bg_color = (100, 120, 160) if is_hovered else (70, 86, 120)
        border_color = (220, 230, 250) if is_hovered else (190, 200, 220)
        border_width = 3 if is_hovered else 1

        pygame.draw.rect(self.screen, bg_color, icon_rect, border_radius=8)
        pygame.draw.rect(self.screen, border_color, icon_rect, width=border_width, border_radius=8)
        deck_text = self.small_font.render(f"Deck {remaining}", True, (245, 245, 245))
        deck_text_rect = deck_text.get_rect(center=icon_rect.center)
        self.screen.blit(deck_text, deck_text_rect)

        # 悬停时显示提示文字
        if is_hovered:
            phase = state.get("phase")
            phase_name = phase.name if hasattr(phase, "name") else str(phase)
            hint_font = self.get_text_font(12)
            if phase_name == "PLAY_P1":
                hint_text = hint_font.render("点击结束出牌", True, (255, 255, 200))
            elif phase_name == "ROUND_END":
                hint_text = hint_font.render("点击补牌", True, (255, 255, 200))
            else:
                hint_text = hint_font.render("牌库", True, (200, 200, 200))
            hint_rect = hint_text.get_rect(centerx=deck_rect.centerx, top=icon_rect.bottom + 5)
            self.screen.blit(hint_text, hint_rect)

    def _draw_replenish_selector(self, state: dict[str, Any]) -> None:
        ui = state.get("ui", {})
        selector = ui.get("replenish_selector") if isinstance(ui, dict) else None
        if not selector or not selector.get("visible"):
            return

        buttons = selector.get("buttons", [])
        if not buttons:
            return

        for button in buttons:
            rect_data = button.get("rect")
            if not rect_data:
                continue
            rect = pygame.Rect(*rect_data)
            pygame.draw.rect(self.screen, (35, 35, 45), rect, border_radius=6)
            pygame.draw.rect(self.screen, (210, 210, 220), rect, width=1, border_radius=6)
            txt = self.small_font.render(str(button.get("label", "")), True, (240, 240, 240))
            self.screen.blit(txt, txt.get_rect(center=rect.center))

    def _draw_bars_and_stats(self, state: dict[str, Any]) -> None:
        p1 = state.get("players", {}).get("P1", {"hp": 10, "mana": 3})
        p2 = state.get("players", {}).get("P2", {"hp": 10, "mana": 3})
        self._draw_hp_bar("P2", p2, x=90, y=70)
        self._draw_hp_bar("P1", p1, x=90, y=self.screen_h - 120)
        # ── 能量石点阵 ────────────────────────────────────────
        self._draw_mana_dots(p2, x=90, y=95)
        self._draw_mana_dots(p1, x=90, y=self.screen_h - 75)
        # ── Buff 栏（P1 右下角）────────────────────────────────
        self._draw_buff_bar(p1, x=920, y=680)
        # ── Buff 栏（P2 右上角）────────────────────────────────
        self._draw_buff_bar(p2, x=920, y=20)

    def _draw_hp_bar(self, player: str, player_state: dict[str, Any], x: int, y: int) -> None:
        hp = int(player_state.get("hp", 10))
        max_hp = int(player_state.get("max_hp", 10))
        bar_w, bar_h = 220, 20
        ratio = 0 if max_hp <= 0 else max(0.0, min(1.0, hp / max_hp))
        fill_w = int(bar_w * ratio)

        pygame.draw.rect(self.screen, (70, 70, 70), pygame.Rect(x, y, bar_w, bar_h), border_radius=6)
        pygame.draw.rect(self.screen, (180, 70, 70), pygame.Rect(x, y, fill_w, bar_h), border_radius=6)
        pygame.draw.rect(self.screen, (200, 200, 200), pygame.Rect(x, y, bar_w, bar_h), width=1, border_radius=6)
        text = self.small_font.render(f"{player} HP: {hp}/{max_hp}", True, (235, 235, 235))
        self.screen.blit(text, (x, y - 22))

    def _draw_timer(self, state: dict[str, Any]) -> None:
        now_ms = pygame.time.get_ticks()
        started_at = int(state.get("phase_started_at_ms", now_ms))
        phase = state.get("phase")
        phase_name = phase.name if hasattr(phase, "name") else str(phase or "")

        # 使用 state["time_left"]（由 main.py 统一倒计时系统计算）
        remain = int(state.get("time_left", 0))

        # 阶段名称显示
        phase_display = phase_name or "UNKNOWN"
        timer_text = self.font.render(f"Phase: {phase_display}  Time: {remain}s", True, (255, 245, 180))
        self.screen.blit(timer_text, (self.screen_w - 360, 24))

    def _draw_last_logs(self, logs: list[dict[str, Any]]) -> None:
        if not logs:
            return
        preview = logs[-3:]
        base_y = self.screen_h - 90
        for i, log in enumerate(preview):
            text = self.small_font.render(
                f"{log.get('player')} {log.get('action')} {log.get('value')} ({log.get('reason')})",
                True,
                (200, 200, 210),
            )
            self.screen.blit(text, (20, base_y + i * 20))

    def _draw_phase_hint(self, state: dict[str, Any]) -> None:
        """在 battlefield 中央显示当前阶段操作提示。"""
        phase = state.get("phase")
        if phase is None:
            return
        phase_name = phase.name if hasattr(phase, "name") else str(phase)
        hints: dict[str, str] = {
            "PLAY_P1": "点击手牌出牌 | 空格/点牌库结束出牌",
            "PLAY_P2": "AI 正在思考...",
            "RESOLVE": "结算中...",
            "REMEDY": "补救阶段 - 拯救自己",
            "REMEDY_AI": "对方补救中...",
            "ROUND_END": "回合结束...",
            "GAME_OVER": "",
        }
        hint_text = hints.get(phase_name, "")
        if not hint_text:
            return

        hint_font = self.get_text_font(18)
        hint_surf = hint_font.render(hint_text, True, (255, 245, 180))
        field = self.zones["battlefield"]
        hint_rect = hint_surf.get_rect(centerx=field.centerx, y=field.centery - 12)
        # 半透明背景条
        bg_rect = hint_rect.inflate(20, 8)
        bg_surf = pygame.Surface((bg_rect.w, bg_rect.h), pygame.SRCALPHA)
        bg_surf.fill((0, 0, 0, 140))
        self.screen.blit(bg_surf, bg_rect.topleft)
        self.screen.blit(hint_surf, hint_rect)

    def _draw_game_over(self, state: dict[str, Any]) -> None:
        """游戏结束时显示胜负结果。

        P2 胜（玩家失败）：显示"无力回天"界面 + 回合数 + "好吧"按钮。
        P1 胜（玩家获胜）：显示"简简单单"风格胜利界面 + "简简单单啊~"按钮。
        """
        phase = state.get("phase")
        if phase is None:
            return
        phase_name = phase.name if hasattr(phase, "name") else str(phase)
        if phase_name != "GAME_OVER":
            self.game_over_btn_rect = None
            return

        winner = state.get("winner", "TIMEOUT")
        # 半透明遮罩
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        cx = self.screen_w // 2
        cy = self.screen_h // 2

        if winner == "P2":
            # ── 玩家失败：无力回天界面 ───────────────────────────
            big_font = self.get_text_font(72, bold=True)
            sub_font = self.get_text_font(24)
            round_font = self.get_text_font(20)

            title_text = "无力回天"
            title_color = (200, 50, 50)

            # 标题阴影
            shadow_surf = big_font.render(title_text, True, (0, 0, 0))
            title_surf = big_font.render(title_text, True, title_color)
            title_cy = cy - 80
            self.screen.blit(shadow_surf, shadow_surf.get_rect(centerx=cx + 3, centery=title_cy + 3))
            self.screen.blit(title_surf, title_surf.get_rect(centerx=cx, centery=title_cy))

            # 回合数
            round_count = int(state.get("round_count", state.get("round_number", 1)))
            round_text = round_font.render(f"坚持了 {round_count} 个回合", True, (220, 220, 220))
            self.screen.blit(round_text, round_text.get_rect(centerx=cx, centery=title_cy + 65))

            # "好吧"按钮
            btn_w, btn_h = 200, 50
            btn_rect = pygame.Rect(cx - btn_w // 2, cy + 40, btn_w, btn_h)
            mouse_pos = pygame.mouse.get_pos()
            hovered = btn_rect.collidepoint(mouse_pos)
            btn_color = (180, 60, 60) if hovered else (140, 40, 40)
            pygame.draw.rect(self.screen, btn_color, btn_rect, border_radius=12)
            pygame.draw.rect(self.screen, (220, 180, 180) if hovered else (180, 140, 140), btn_rect, width=2, border_radius=12)

            btn_font = self.get_text_font(22, bold=True)
            btn_label = btn_font.render("好吧", True, (255, 255, 255))
            self.screen.blit(btn_label, btn_label.get_rect(center=btn_rect.center))
            self.game_over_btn_rect = btn_rect

        elif winner == "P1":
            # ── 玩家获胜：简简单单风格胜利界面 ──────────────────
            big_font = self.get_text_font(48, bold=True)
            sub_font = self.get_text_font(22)
            round_font = self.get_text_font(20)

            # 标题
            title_text = "您战胜了强大的对手"
            title_color = (255, 215, 0)

            # 标题阴影
            shadow_surf = big_font.render(title_text, True, (0, 0, 0))
            title_surf = big_font.render(title_text, True, title_color)
            title_cy = cy - 90
            self.screen.blit(shadow_surf, shadow_surf.get_rect(centerx=cx + 3, centery=title_cy + 3))
            self.screen.blit(title_surf, title_surf.get_rect(centerx=cx, centery=title_cy))

            # 副标题
            sub_text = "恭喜胜利！"
            sub_surf = sub_font.render(sub_text, True, (220, 220, 220))
            sub_shadow = sub_font.render(sub_text, True, (0, 0, 0))
            self.screen.blit(sub_shadow, sub_shadow.get_rect(centerx=cx + 2, centery=title_cy + 45))
            self.screen.blit(sub_surf, sub_surf.get_rect(centerx=cx, centery=title_cy + 43))

            # 回合数
            round_count = int(state.get("round_count", state.get("round_number", 1)))
            round_text = round_font.render(f"用了 {round_count} 个回合", True, (200, 200, 200))
            self.screen.blit(round_text, round_text.get_rect(centerx=cx, centery=title_cy + 78))

            # ── 成就解锁列表 ───────────────────────────────────
            unlocked: list[str] = state.get("unlocked_achievements", [])
            ach_y_start = title_cy + 110
            if unlocked:
                ach_font = self.get_text_font(20, bold=True)
                y_offset = ach_y_start
                for name in unlocked:
                    ach_text = f"🏆 成就解锁：{name}"
                    ach_surf = ach_font.render(ach_text, True, (255, 215, 0))
                    ach_shadow = ach_font.render(ach_text, True, (0, 0, 0))
                    self.screen.blit(ach_shadow, ach_shadow.get_rect(centerx=cx + 2, centery=y_offset + 2))
                    self.screen.blit(ach_surf, ach_surf.get_rect(centerx=cx, centery=y_offset))
                    y_offset += 36

            # "简简单单啊~"按钮
            btn_w, btn_h = 260, 55
            btn_rect = pygame.Rect(cx - btn_w // 2, cy + 60, btn_w, btn_h)
            mouse_pos = pygame.mouse.get_pos()
            hovered = btn_rect.collidepoint(mouse_pos)
            btn_color = (70, 160, 220) if hovered else (50, 130, 200)
            pygame.draw.rect(self.screen, btn_color, btn_rect, border_radius=15)
            pygame.draw.rect(self.screen, (140, 200, 255) if hovered else (100, 170, 230), btn_rect, width=2, border_radius=15)

            btn_font = self.get_text_font(24, bold=True)
            btn_label = btn_font.render("简简单单啊~", True, (255, 255, 255))
            self.screen.blit(btn_label, btn_label.get_rect(center=btn_rect.center))
            self.victory_btn_rect = btn_rect
            self.game_over_btn_rect = None

        else:
            # ── 平局 ──────────────────────────────────────────────
            big_font = self.get_text_font(52, bold=True)
            sub_font = self.get_text_font(24)

            title_text = "DRAW"
            title_color = (180, 180, 180)
            sub_text = "平局"

            title_surf = big_font.render(title_text, True, title_color)
            sub_surf = sub_font.render(sub_text, True, (220, 220, 220))

            shadow_surf = big_font.render(title_text, True, (0, 0, 0))
            self.screen.blit(shadow_surf, shadow_surf.get_rect(centerx=cx + 3, centery=cy - 27))
            self.screen.blit(title_surf, title_surf.get_rect(centerx=cx, centery=cy - 30))
            self.screen.blit(sub_surf, sub_surf.get_rect(centerx=cx, centery=cy + 35))
            self.game_over_btn_rect = None

    # ── 战报播报（非阻塞，2.5秒自动消失）────────────────────────────

    def _draw_toasts(self, state: dict[str, Any]) -> None:
        """绘制战报播报消息。

        从 state["toasts"] 读取队列，显示 2.5 秒后自动清除。
        多条消息垂直排列，不阻塞游戏循环。
        """
        toasts: list[dict[str, Any]] = state.get("toasts", [])
        if not toasts:
            return

        now = pygame.time.get_ticks()
        toast_duration_ms = 2500
        toast_font = self.get_text_font(22, bold=True)

        # 过滤并清理过期 toast
        active = [t for t in toasts if now - t.get("time", 0) < toast_duration_ms]
        state["toasts"] = active

        if not active:
            return

        for i, toast in enumerate(active):
            elapsed = now - toast.get("time", 0)
            # 最后 500ms 淡出
            if elapsed > toast_duration_ms - 500:
                alpha = int(255 * (toast_duration_ms - elapsed) / 500)
                alpha = max(0, min(255, alpha))
            else:
                alpha = 255

            text = str(toast.get("text", ""))
            if not text:
                continue

            text_surf = toast_font.render(text, True, (255, 255, 255))
            text_w = text_surf.get_width()
            text_h = text_surf.get_height()

            # 半透明黑底
            pad_x, pad_y = 20, 10
            bg_w = text_w + pad_x * 2
            bg_h = text_h + pad_y * 2
            bg_surf = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
            bg_surf.fill((0, 0, 0, min(180, alpha)))
            # 圆角效果（用矩形近似）
            pygame.draw.rect(bg_surf, (255, 215, 0, min(200, alpha)), bg_surf.get_rect(), width=2, border_radius=8)

            # 垂直排列，从屏幕中央偏上开始
            toast_x = (self.screen_w - bg_w) // 2
            toast_y = 80 + i * (bg_h + 8)

            # 设置透明度
            text_surf.set_alpha(alpha)

            self.screen.blit(bg_surf, (toast_x, toast_y))
            self.screen.blit(text_surf, (toast_x + pad_x, toast_y + pad_y))

    # ── 能量石点阵（动态 max_mana）──────────────────────────────────

    def _draw_mana_dots(self, player_state: dict[str, Any], x: int, y: int) -> None:
        """绘制能量石点阵，动态读取 max_mana 决定总槽位数。

        总点数 = max_mana（初始 5，增益卡打出后可扩展至 10）。
        黄点 #FFD700 = current_mana（可用精力）。
        剩余槽位显示深灰 #333333。
        """
        max_mana = int(player_state.get("max_mana", 5))
        current_mana = int(player_state.get("current_mana", 0))
        # 硬顶不超过 10（与 MANA_HARD_CAP 对齐）
        max_mana = min(max_mana, 10)

        dot_r = 6  # 半径 6px → 直径 12px
        gap_x = 4  # 水平间距
        gap_y = 4  # 行间距
        cols = 5
        color_available = (255, 215, 0)   # #FFD700 黄色（可用）
        color_empty = (45, 45, 45)        # #2D2D2D 深灰（空位）
        color_cap = (60, 60, 60)          # 灰色（超出当前 max_mana 的预留槽）

        for i in range(10):
            row = i // cols
            col = i % cols
            cx = x + col * (dot_r * 2 + gap_x) + dot_r
            cy = y + row * (dot_r * 2 + gap_y) + dot_r
            if i < max_mana:
                color = color_available if i < current_mana else color_empty
            else:
                color = color_cap
            pygame.draw.circle(self.screen, color, (cx, cy), dot_r)

    # ── Buff 栏 ────────────────────────────────────────────────────

    def _draw_buff_bar(self, player_state: dict[str, Any], x: int, y: int) -> None:
        """绘制 Buff 图标栏，横向排列。

        遍历 player_state["buffs"] 列表，每条 buff 绘制：
          - 图标（优先图片，缺失则用首字母色块代替）
          - 名称 + 数值
          - 剩余回合标注（duration=-1 显示"永久"）
        层级在卡牌之上，不遮挡战场。
        """
        buffs = player_state.get("buffs")
        if not buffs or not isinstance(buffs, list):
            return

        active_buffs = [b for b in buffs if isinstance(b, dict) and int(b.get("value", 0)) > 0]
        if not active_buffs:
            return

        icon_size = 36
        spacing = 6
        mouse_pos = pygame.mouse.get_pos()
        tooltip_info: tuple[list[str], pygame.Rect] | None = None

        cx = x
        for buff in active_buffs:
            buff_type = str(buff.get("type", ""))
            buff_value = int(buff.get("value", 0))
            icon_code = str(buff.get("icon_code", buff_type[:1].lower()))
            duration = int(buff.get("duration", 0))

            icon_rect = pygame.Rect(cx, y, icon_size, icon_size)

            # 绘制图标
            img = self._buff_images.get(buff_type)
            if img is not None:
                scaled = pygame.transform.smoothscale(img, (icon_size, icon_size))
                self.screen.blit(scaled, icon_rect.topleft)
            else:
                self._draw_buff_placeholder(self.screen, icon_code, icon_rect)

            # 边框颜色按类型区分
            border_color = self._buff_border_color(buff_type)
            pygame.draw.rect(self.screen, border_color, icon_rect, width=2, border_radius=5)

            # 数值标签（右下角）
            val_font = self.get_text_font(11, bold=True)
            val_surf = val_font.render(str(buff_value), True, (255, 255, 255))
            val_bg = pygame.Surface((val_surf.get_width() + 4, val_surf.get_height() + 2), pygame.SRCALPHA)
            val_bg.fill((0, 0, 0, 160))
            self.screen.blit(val_bg, (icon_rect.right - val_bg.get_width() - 1, icon_rect.bottom - val_bg.get_height() - 1))
            self.screen.blit(val_surf, (icon_rect.right - val_surf.get_width() - 3, icon_rect.bottom - val_surf.get_height() - 2))

            # 回合标签（图标下方）
            if duration == -1:
                dur_text = ""
            elif duration > 0:
                dur_text = f"{duration}R"
            else:
                dur_text = ""
            if dur_text:
                dur_font = self.get_text_font(10)
                dur_surf = dur_font.render(dur_text, True, (200, 200, 200))
                self.screen.blit(dur_surf, (icon_rect.x, icon_rect.bottom + 1))

            # Hover 检测
            if icon_rect.collidepoint(mouse_pos):
                tooltip_info = self._build_buff_tooltip(buff, icon_rect)

            cx += icon_size + spacing

        # 绘制 tooltip
        if tooltip_info is not None:
            text_lines, anchor_rect = tooltip_info
            self._draw_buff_tooltip(self.screen, text_lines, mouse_pos)

    @staticmethod
    def _buff_border_color(buff_type: str) -> tuple[int, int, int]:
        """根据 buff 类型返回边框颜色。"""
        color_map = {
            "shield": (70, 130, 230),
            "heal_over_time": (50, 200, 80),
            "heal": (50, 200, 80),
            "dmg_reduce": (200, 170, 50),
            "burn": (220, 80, 30),
            "mana_up": (180, 130, 255),
        }
        return color_map.get(buff_type, (120, 120, 120))

    @staticmethod
    def _draw_buff_placeholder(surface: pygame.Surface, icon_code: str, rect: pygame.Rect) -> None:
        """Buff 图标占位绘制：根据 icon_code 首字母绘制色块。

        若 icon_code 为空则用 "?" 兜底，杜绝空白 Bug。
        """
        code = icon_code.strip().lower() if icon_code else "?"
        first_char = code[0] if code else "?"

        color_map = {
            "s": (40, 80, 180),     # shield → 蓝
            "h": (30, 140, 60),     # heal → 绿
            "d": (160, 140, 30),    # dmg_reduce → 暗金
            "b": (180, 50, 20),     # burn → 红
            "m": (120, 80, 200),    # mana_up → 紫
        }
        bg = color_map.get(first_char, (80, 80, 80))
        surface.fill(bg, rect)

        # 首字母文字
        font = pygame.font.Font(None, max(16, rect.width // 2))
        text = font.render(first_char.upper(), True, (255, 255, 255))
        text_rect = text.get_rect(center=rect.center)
        surface.blit(text, text_rect)

    @staticmethod
    def _build_buff_tooltip(
        buff: dict[str, Any],
        anchor_rect: pygame.Rect,
    ) -> tuple[list[str], pygame.Rect]:
        """构建 buff tooltip 数据。"""
        buff_type = str(buff.get("type", ""))
        buff_value = int(buff.get("value", 0))
        duration = int(buff.get("duration", 0))

        name_map = {
            "shield": "护盾",
            "heal_over_time": "持续治疗",
            "heal": "治疗",
            "dmg_reduce": "减伤",
            "burn": "灼烧",
            "mana_up": "精力提升",
        }
        display_name = name_map.get(buff_type, buff_type)

        if buff_type == "shield":
            lines = [
                f"[{display_name}]",
                f"抵挡伤害：{buff_value}",
                "持续时间：永久",
            ]
        elif buff_type == "dmg_reduce":
            lines = [
                f"[{display_name}]",
                f"减伤比例：{buff_value}%",
                f"剩余回合：{duration}",
            ]
        elif buff_type == "burn":
            lines = [
                f"[{display_name}]",
                f"每回合伤害：{buff_value}",
                f"剩余回合：{duration}",
            ]
        else:
            dur_str = "永久" if duration == -1 else f"{duration}回合"
            lines = [f"[{display_name}]", f"数值：{buff_value}", f"剩余：{dur_str}"]
        return lines, anchor_rect

    def _draw_buff_tooltip(
        self,
        surface: pygame.Surface,
        lines: list[str],
        mouse_pos: tuple[int, int],
    ) -> None:
        """绘制 buff tooltip（白色背景 + 黑色文字 + 圆角）。"""
        font = self.get_text_font(14)
        pad = 8
        line_h = font.get_height() + 3
        max_w = max(font.size(line)[0] for line in lines) if lines else 100
        tip_w = max_w + pad * 2
        tip_h = len(lines) * line_h + pad * 2

        mx, my = mouse_pos[0], mouse_pos[1]
        tx = mx + 12
        ty = my - tip_h - 8
        if tx + tip_w > self.screen_w:
            tx = max(0, mx - tip_w - 12)
        if ty < 0:
            ty = my + 18

        tip_rect = pygame.Rect(tx, ty, tip_w, tip_h)
        tip_bg = pygame.Surface((tip_w, tip_h), pygame.SRCALPHA)
        tip_bg.fill((255, 255, 255, 235))
        surface.blit(tip_bg, tip_rect.topleft)
        pygame.draw.rect(surface, (180, 180, 180), tip_rect, width=1, border_radius=8)

        for i, line in enumerate(lines):
            txt_surf = font.render(line, True, (30, 30, 30))
            surface.blit(txt_surf, (tx + pad, ty + pad + i * line_h))

    # ── 补救回合专属 UI 渲染 ──────────────────────────────────────

    def _draw_remedy_overlay(self, state: dict[str, Any]) -> None:
        """补救回合专属渲染层：深蓝边框 + 警告文字 + 倒计时。

        REMEDY：P1 濒死，"你需要拯救自己"
        REMEDY_AI：P2 濒死，"对方尝试自救中..."
        必须在所有元素绘制完成后调用，确保覆盖在最上方。
        """
        phase = state.get("phase")
        is_remedy_p1 = False
        is_remedy_ai = False
        if phase is not None:
            phase_name = phase.name if hasattr(phase, "name") else str(phase)
            is_remedy_p1 = phase_name == "REMEDY"
            is_remedy_ai = phase_name == "REMEDY_AI"
        if not is_remedy_p1 and not is_remedy_ai:
            return

        w, h = self.screen.get_size()

        # 1. 深蓝色边框（覆盖屏幕四周边缘，宽度 15px）
        border_color = (0, 0, 100)
        pygame.draw.rect(self.screen, border_color, (0, 0, w, h), 15)

        if is_remedy_p1:
            # P1 补救：天蓝色警告文字居中
            warning_font = self.get_text_font(42, bold=True)
            warning_text = warning_font.render("你需要拯救自己", True, (135, 206, 250))
            text_rect = warning_text.get_rect(center=(w // 2, h // 2 - 30))
            # 文字阴影
            shadow_surf = warning_font.render("你需要拯救自己", True, (0, 0, 0))
            self.screen.blit(shadow_surf, shadow_surf.get_rect(centerx=text_rect.centerx + 3, centery=text_rect.centery + 3))
            self.screen.blit(warning_text, text_rect)

            # 3. 倒计时显示（文字正下方）
            time_left = int(state.get("time_left", 30))
            time_font = self.get_text_font(28)
            time_text = time_font.render(f"剩余时间: {time_left}s", True, (255, 255, 255))
            time_rect = time_text.get_rect(center=(w // 2, h // 2 + 30))
            # 时间文字阴影
            time_shadow = time_font.render(f"剩余时间: {time_left}s", True, (0, 0, 0))
            self.screen.blit(time_shadow, time_shadow.get_rect(centerx=time_rect.centerx + 2, centery=time_rect.centery + 2))
            self.screen.blit(time_text, time_rect)
        elif is_remedy_ai:
            # AI 补救：红色警告文字居中
            warning_font = self.get_text_font(38, bold=True)
            warning_text = warning_font.render("对方尝试自救中...", True, (255, 120, 120))
            text_rect = warning_text.get_rect(center=(w // 2, h // 2 - 15))
            # 文字阴影
            shadow_surf = warning_font.render("对方尝试自救中...", True, (0, 0, 0))
            self.screen.blit(shadow_surf, shadow_surf.get_rect(centerx=text_rect.centerx + 3, centery=text_rect.centery + 3))
            self.screen.blit(warning_text, text_rect)

            # 思考提示
            sub_font = self.get_text_font(22)
            dot_count = (pygame.time.get_ticks() // 500) % 4
            dots = "." * dot_count
            sub_text = sub_font.render(f"AI 思考中{dots}", True, (200, 200, 200))
            self.screen.blit(sub_text, sub_text.get_rect(center=(w // 2, h // 2 + 35)))

    # ── 补牌动画渲染 ───────────────────────────────────────────────

    def _get_draw_anim_positions(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """计算补牌动画的起点和终点坐标。

        Returns:
            (start_pos, end_pos): 起点(牌库区中心)，终点(手牌区首张位置)
        """
        deck_zone = self.zones["deck"]
        # 牌库图标区域中心（约在 deck zone 偏上位置）
        start_x = deck_zone.centerx
        start_y = deck_zone.y + 50

        # 手牌区首张卡位置（与 _draw_hand_cards 保持一致）
        hand_start_x = 280
        hand_y = 550
        end_x = hand_start_x
        end_y = hand_y

        return (start_x, start_y), (end_x, end_y)

    def _draw_draw_animation(self, state: dict[str, Any]) -> None:
        """渲染补牌动画：卡背从牌库飞向手牌区。

        动画期间数据层不变，动画结束后由 main.py 统一更新手牌。
        """
        anim = state.get("draw_anim")
        if not anim or not anim.get("active", False):
            return

        progress = float(anim.get("progress", 0.0))
        if progress <= 0:
            return

        start_pos, end_pos = self._get_draw_anim_positions()
        sx, sy = start_pos
        ex, ey = end_pos

        # 贝塞尔缓动曲线（ease-out 效果）
        t = 1.0 - (1.0 - progress) * (1.0 - progress)
        curr_x = sx + (ex - sx) * t
        curr_y = sy + (ey - sy) * t

        # 获取卡背图片
        img = self.asset_manager.get_card_back_anim()
        card_w, card_h = img.get_width(), img.get_height()

        # 绘制主卡（居中于当前位置）
        self.screen.blit(img, (int(curr_x - card_w // 2), int(curr_y - card_h // 2)))

        # 堆叠视觉效果（多张牌时绘制副卡偏移）
        count = int(anim.get("count", 1))
        if count > 1:
            stack_count = min(count - 1, 2)  # 最多显示2张偏移副卡
            for i in range(stack_count):
                offset_x = (i + 1) * 8
                offset_y = (i + 1) * 4
                # 副卡半透明
                ghost = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
                ghost.blit(img, (0, 0))
                ghost.set_alpha(160)  # 透明度
                self.screen.blit(ghost, (int(curr_x - card_w // 2 + offset_x), int(curr_y - card_h // 2 + offset_y)))

    # ── 悬停粒子系统 ───────────────────────────────────────────────

    def _update_and_draw_particles(self) -> None:
        """更新粒子状态并绘制到屏幕，同时清理已消亡粒子。"""
        # 更新所有粒子
        for particle in self._particles:
            particle.update()
        # 移除已消亡粒子
        self._particles = [p for p in self._particles if p.life > 0]
        # 绘制剩余粒子
        for particle in self._particles:
            particle.draw(self.screen)

    # ── 认输按钮 ──────────────────────────────────────────────────

    def _draw_surrender_button(self, state: dict[str, Any]) -> None:
        """在对战/补救阶段绘制认输按钮，仅右下角显示。

        按钮 Rect 存入 self.surrender_btn_rect 供 input_router 检测。
        """
        phase = state.get("phase")
        if phase is None:
            return
        phase_name = phase.name if hasattr(phase, "name") else str(phase)
        if phase_name not in ("PLAY_P1", "PLAY_P2", "REMEDY"):
            self.surrender_btn_rect = None
            state["surrender_btn_rect"] = None
            return

        btn_rect = pygame.Rect(self.screen_w - 100, 20, 80, 36)
        mouse_pos = pygame.mouse.get_pos()
        hovered = btn_rect.collidepoint(mouse_pos)
        color = (200, 50, 50) if hovered else (150, 30, 30)
        pygame.draw.rect(self.screen, color, btn_rect, border_radius=8)
        pygame.draw.rect(self.screen, (220, 180, 180) if hovered else (180, 140, 140), btn_rect, width=1, border_radius=8)

        font = self.get_text_font(16, bold=True)
        label = font.render("认输", True, (255, 255, 255))
        label_rect = label.get_rect(center=btn_rect.center)
        self.screen.blit(label, label_rect)
        self.surrender_btn_rect = btn_rect
        state["surrender_btn_rect"] = btn_rect

    # ── 暂停按钮 ──────────────────────────────────────────────────

    def _draw_pause_button(self, state: dict[str, Any]) -> None:
        """在对战阶段绘制暂停按钮，位于认输按钮正下方。"""
        phase = state.get("phase")
        if phase is None:
            return
        phase_name = phase.name if hasattr(phase, "name") else str(phase)
        if phase_name not in ("PLAY_P1", "PLAY_P2", "REMEDY"):
            self.pause_btn_rect = None
            state["pause_btn_rect"] = None
            return

        # 认输按钮位置：右上角 (screen_w-100, 20, 80, 36)
        btn_rect = pygame.Rect(self.screen_w - 100, 64, 80, 36)
        mouse_pos = pygame.mouse.get_pos()
        hovered = btn_rect.collidepoint(mouse_pos)
        color = (165, 113, 78) if hovered else (139, 90, 43)
        pygame.draw.rect(self.screen, color, btn_rect, border_radius=8)
        pygame.draw.rect(self.screen, (200, 170, 130) if hovered else (170, 140, 100), btn_rect, width=1, border_radius=8)

        font = self.get_text_font(16, bold=True)
        label = font.render("暂停", True, (255, 255, 255))
        label_rect = label.get_rect(center=btn_rect.center)
        self.screen.blit(label, label_rect)
        self.pause_btn_rect = btn_rect
        state["pause_btn_rect"] = btn_rect

    # ── 暂停面板 ──────────────────────────────────────────────────

    def draw_pause_panel(self, state: dict[str, Any]) -> None:
        """绘制暂停面板（灰底 400×320，居中白色区域显示随机卡牌，返回游戏按钮）。

        暂停面板在 main.py 中暂停状态下调用，覆盖在游戏画面之上。
        """
        import json as _json
        mouse_pos = pygame.mouse.get_pos()

        # 半透明遮罩
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        # 灰底面板 400×320，屏幕居中
        pw, ph = 400, 320
        panel_x = (self.screen_w - pw) // 2
        panel_y = (self.screen_h - ph) // 2
        panel_rect = pygame.Rect(panel_x, panel_y, pw, ph)
        pygame.draw.rect(self.screen, (180, 180, 180), panel_rect, border_radius=12)
        pygame.draw.rect(self.screen, (120, 120, 120), panel_rect, width=2, border_radius=12)

        # 白色区域 200×200，距顶部 20px，水平居中
        white_w, white_h = 200, 200
        white_x = panel_x + (pw - white_w) // 2
        white_y = panel_y + 20
        white_rect = pygame.Rect(white_x, white_y, white_w, white_h)
        pygame.draw.rect(self.screen, (255, 255, 255), white_rect, border_radius=8)

        # 在白色区域内随机渲染一张卡牌（缩放到 100×100），首次打开暂停时随机
        if self._pause_card_seed is None:
            self._pause_card_seed = random.randint(1, 54)
            self._pause_card_surf = None  # 重置缓存

        if self._pause_card_surf is None:
            card_surf = self._load_random_plant_image(self._pause_card_seed)
            if card_surf is not None:
                self._pause_card_surf = pygame.transform.smoothscale(card_surf, (100, 100))
            else:
                self._pause_card_surf = pygame.Surface((100, 100), pygame.SRCALPHA)
                self._pause_card_surf.fill((200, 200, 200))

        # 居中绘制在白色区域
        card_x = white_x + (white_w - 100) // 2
        card_y = white_y + (white_h - 100) // 2
        self.screen.blit(self._pause_card_surf, (card_x, card_y))

        # 返回游戏按钮：距底部 20px，水平居中
        btn_w, btn_h = 120, 36
        btn_x = panel_x + (pw - btn_w) // 2
        btn_y = white_y + white_h + (ph - 20 - (white_y + white_h - panel_y) - btn_h) // 2
        # 更精确：白区域底部 y = white_y + 200, 面板底部 = panel_y + 320
        # 间距 = panel_y + 320 - (white_y + 200) = 320 - 20 - 200 = 100px
        # 按钮距底部 20px: btn_y = panel_y + 320 - 20 - 36 = panel_y + 264
        btn_y = panel_y + ph - 20 - btn_h
        self.pause_back_btn = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

        hovered = self.pause_back_btn.collidepoint(mouse_pos)
        btn_color = (139, 90, 43) if hovered else (110, 75, 30)
        pygame.draw.rect(self.screen, btn_color, self.pause_back_btn, border_radius=8)
        pygame.draw.rect(self.screen, (200, 170, 130) if hovered else (170, 140, 100), self.pause_back_btn, width=1, border_radius=8)

        font = self.get_text_font(16, bold=True)
        label = font.render("返回游戏", True, (255, 255, 255))
        label_rect = label.get_rect(center=self.pause_back_btn.center)
        self.screen.blit(label, label_rect)

    def _load_random_plant_image(self, card_index: int) -> pygame.Surface | None:
        """根据卡牌索引加载植物图片。"""
        import json as _json
        cards_path = Path("config/cards.json")
        if not cards_path.exists():
            return None
        try:
            with open(cards_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            cards = data.get("cards", [])
            if not cards:
                return None
            card = cards[(card_index - 1) % len(cards)]
            image_file = card.get("image_file", "")
            card_id = card.get("id", card_index)
            faction = card.get("faction", "")
            if image_file:
                img_path = get_resource_path("assets/cards") / image_file
                if img_path.exists():
                    return pygame.image.load(str(img_path)).convert_alpha()
            # 降级通过 card_id
            img_path = get_resource_path("assets/cards") / f"{card_id}.png"
            if img_path.exists():
                return pygame.image.load(str(img_path)).convert_alpha()
            return None
        except (OSError, _json.JSONDecodeError, IndexError):
            return None

    # ── 设置界面 ──────────────────────────────────────────────────

    def draw_settings(self, settings: dict[str, Any]) -> pygame.Rect:
        """绘制设置面板（半透明遮罩 + 居中面板 + 滑块 + 开关 + 返回按钮）。

        Args:
            settings: 当前设置字典

        Returns:
            面板的 Rect（供外部碰撞检测）
        """
        mouse_pos = pygame.mouse.get_pos()

        # 半透明遮罩
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        # 面板（居中 500×380）
        pw, ph = 500, 380
        panel_rect = pygame.Rect(
            (self.screen_w - pw) // 2,
            (self.screen_h - ph) // 2,
            pw, ph,
        )
        pygame.draw.rect(self.screen, (40, 40, 60), panel_rect, border_radius=15)
        pygame.draw.rect(self.screen, (100, 100, 150), panel_rect, 3, border_radius=15)

        # 标题
        title_font = self.get_text_font(28, bold=True)
        title_surf = title_font.render("⚙ 设置", True, (255, 255, 255))
        self.screen.blit(title_surf, (panel_rect.centerx - title_surf.get_width() // 2, panel_rect.top + 20))

        # 分隔线
        sep_y = panel_rect.top + 60
        pygame.draw.line(
            self.screen, (100, 100, 150),
            (panel_rect.left + 30, sep_y), (panel_rect.right - 30, sep_y), 1,
        )

        # 控件起始 Y
        ctrl_x = panel_rect.left + 50
        ctrl_w = pw - 100  # 滑轨宽度
        y = panel_rect.top + 80

        # 1. BGM 音量滑块
        self._draw_slider(self.screen, settings, "BGM音量", "bgm_volume",
                          ctrl_x, y, ctrl_w, mouse_pos)
        y += 65

        # 2. 音效音量滑块
        self._draw_slider(self.screen, settings, "音效音量", "sfx_volume",
                          ctrl_x, y, ctrl_w, mouse_pos)
        y += 65

        # 3. BGM 静音开关
        self._draw_toggle(self.screen, settings, "关闭BGM", "bgm_muted",
                          ctrl_x, y, mouse_pos)
        y += 55

        # 4. 亮度滑块
        self._draw_slider(self.screen, settings, "屏幕亮度", "screen_brightness",
                          ctrl_x, y, ctrl_w, mouse_pos, min_val=0.3, max_val=1.0, pct=False)

        # 返回按钮
        btn_w, btn_h = 180, 42
        btn_rect = pygame.Rect(
            panel_rect.centerx - btn_w // 2,
            panel_rect.bottom - btn_h - 20,
            btn_w, btn_h,
        )
        btn_hovered = btn_rect.collidepoint(mouse_pos)
        btn_color = (80, 160, 200) if btn_hovered else (55, 120, 180)
        pygame.draw.rect(self.screen, btn_color, btn_rect, border_radius=10)
        pygame.draw.rect(self.screen, (180, 210, 240) if btn_hovered else (130, 160, 200),
                         btn_rect, width=2, border_radius=10)
        btn_font = self.get_text_font(18, bold=True)
        btn_label = btn_font.render("返回", True, (255, 255, 255))
        self.screen.blit(btn_label, btn_label.get_rect(center=btn_rect.center))
        self.settings_back_btn = btn_rect

        return panel_rect

    def _draw_slider(
        self,
        surface: pygame.Surface,
        settings: dict[str, Any],
        label: str,
        key: str,
        x: int,
        y: int,
        track_w: int,
        mouse_pos: tuple[int, int],
        min_val: float = 0.0,
        max_val: float = 1.0,
        pct: bool = True,
    ) -> None:
        """绘制滑块控件并处理拖拽交互。

        Args:
            pct: True 显示百分比，False 显示 0.1 精度小数
        """
        value = float(settings.get(key, 0.5))
        value = max(min_val, min(max_val, value))

        # 标签 + 数值
        if pct:
            display_val = f"{int(value * 100)}%"
        else:
            display_val = f"{value:.1f}"
        text_str = f"{label}: {display_val}"
        label_font = self.get_text_font(17)
        label_surf = label_font.render(text_str, True, (220, 220, 230))
        surface.blit(label_surf, (x, y))

        # 滑轨
        track_y = y + 30
        track_rect = pygame.Rect(x, track_y, track_w, 8)
        pygame.draw.rect(surface, (70, 70, 90), track_rect, border_radius=4)

        # 填充部分
        normalized = (value - min_val) / max(max_val - min_val, 1e-9)
        fill_w = int(normalized * track_w)
        if fill_w > 0:
            fill_rect = pygame.Rect(x, track_y, fill_w, 8)
            pygame.draw.rect(surface, (80, 160, 240), fill_rect, border_radius=4)

        # 滑块手柄
        handle_x = x + fill_w
        handle_y = track_y + 4
        # 手柄悬停放大
        handle_rect = pygame.Rect(handle_x - 10, handle_y - 10, 20, 20)
        hovered = handle_rect.collidepoint(mouse_pos) or track_rect.collidepoint(mouse_pos)
        handle_r = 9 if hovered else 7
        pygame.draw.circle(surface, (120, 200, 255), (handle_x, handle_y), handle_r)
        pygame.draw.circle(surface, (255, 255, 255), (handle_x, handle_y), handle_r, 2)

        # 拖拽处理
        if pygame.mouse.get_pressed()[0]:
            if self._slider_dragging == key:
                # 持续拖拽
                new_val = min_val + (mouse_pos[0] - x) / max(track_w, 1) * (max_val - min_val)
                new_val = max(min_val, min(max_val, new_val))
                settings[key] = round(new_val, 2)
            elif (track_rect.inflate(0, 16).collidepoint(mouse_pos)
                  or handle_rect.collidepoint(mouse_pos)):
                self._slider_dragging = key
                new_val = min_val + (mouse_pos[0] - x) / max(track_w, 1) * (max_val - min_val)
                new_val = max(min_val, min(max_val, new_val))
                settings[key] = round(new_val, 2)

    def _draw_toggle(
        self,
        surface: pygame.Surface,
        settings: dict[str, Any],
        label: str,
        key: str,
        x: int,
        y: int,
        mouse_pos: tuple[int, int],
    ) -> None:
        """绘制开关控件。

        点击交互由 handle_settings_click() 统一处理。
        此方法记录 toggle 矩形到 self._toggle_rects 供碰撞检测使用。
        """
        is_on = bool(settings.get(key, False))

        # 标签
        label_font = self.get_text_font(17)
        label_surf = label_font.render(label, True, (220, 220, 230))
        surface.blit(label_surf, (x, y))

        # 开关轨道
        toggle_w, toggle_h = 56, 28
        toggle_x = x + 200
        toggle_rect = pygame.Rect(toggle_x, y, toggle_w, toggle_h)
        bg_color = (70, 180, 100) if is_on else (90, 90, 100)
        pygame.draw.rect(surface, bg_color, toggle_rect, border_radius=14)

        # 圆形手柄
        knob_r = 11
        knob_x = toggle_x + toggle_w - 16 if is_on else toggle_x + 16
        knob_y = y + toggle_h // 2
        pygame.draw.circle(surface, (255, 255, 255), (knob_x, knob_y), knob_r)

        # 状态文字
        status_text = "ON" if is_on else "OFF"
        status_color = (180, 255, 200) if is_on else (160, 160, 170)
        status_surf = label_font.render(status_text, True, status_color)
        surface.blit(status_surf, (toggle_x + toggle_w + 12, y + 3))

        # 记录 toggle 矩形供 handle_settings_click() 使用
        if not hasattr(self, "_toggle_rects"):
            self._toggle_rects: dict[str, pygame.Rect] = {}
        self._toggle_rects[key] = toggle_rect

    def handle_settings_mouse_up(self) -> None:
        """鼠标释放时清除拖拽状态。"""
        self._slider_dragging = None

    def handle_settings_click(self, pos: tuple[int, int], settings: dict[str, Any]) -> str | None:
        """处理设置面板内的鼠标点击事件。

        Returns:
            "back" 表示点击了返回按钮，None 表示其他
        """
        if self.settings_back_btn is not None and self.settings_back_btn.collidepoint(pos):
            return "back"

        # 检查 toggle 开关点击（切换布尔值）
        toggle_rects: dict[str, pygame.Rect] = getattr(self, "_toggle_rects", {})
        for key, rect in toggle_rects.items():
            if rect.collidepoint(pos):
                settings[key] = not bool(settings.get(key, False))
                return None

        return None
