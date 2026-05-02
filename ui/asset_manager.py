from __future__ import annotations

from pathlib import Path
from typing import Any

import pygame

from utils.path_utils import get_resource_path


class AssetManager:
    CARD_SIZE = (80, 120)
    # 阵营 → 英文文件名前缀（对应 assets/images/borders/ 下的文件）
    _FACTION_BG_MAP: dict[str, str] = {
        "法师": "bg_mage",
        "射手": "bg_archer",
        "坦克": "bg_tank",
        "辅助": "bg_support",
    }
    _FACTION_COLORS: dict[str, tuple[int, int, int]] = {
        "法师": (138, 43, 226),   # 紫
        "射手": (34, 139, 34),    # 绿
        "坦克": (139, 69, 19),    # 棕
        "辅助": (255, 215, 0),    # 金
    }

    def __init__(self, asset_root: str = "") -> None:
        self.asset_root = Path(asset_root) if asset_root else get_resource_path("assets")
        self.images: dict[str, pygame.Surface] = {}
        self.fonts: dict[int, pygame.font.Font] = {}
        # 卡牌背面 surface（懒加载）
        self._card_back: pygame.Surface | None = None
        # 卡背动画专用 surface（统一尺寸，懒加载）
        self._card_back_anim: pygame.Surface | None = None
        # 数值底图缓存（bg_energy / bg_atk / bg_limit）
        self._stat_badges: dict[str, pygame.Surface] = {}

    # ── 公共接口 ──────────────────────────────────────────────────

    def get_card_surface(self, card_id: int | str, faction: Any, image_file: str = "") -> pygame.Surface:
        """获取卡牌正面 Surface。

        优先级：image_file 指定路径 > assets/cards/<image_file> > 阵营背景图 > 纯色占位。
        """
        key = f"card::{card_id}::{self._normalize_faction_key(faction)}"
        cached = self.images.get(key)
        if cached is not None:
            return cached

        # 1. 优先使用 image_file（Card.image_file 字段）
        img_name = image_file if image_file else ""
        if img_name:
            card_img_path = self.asset_root / "cards" / img_name
            if card_img_path.exists():
                surface = pygame.image.load(str(card_img_path)).convert_alpha()
                surface = pygame.transform.smoothscale(surface, self.CARD_SIZE)
                self.images[key] = surface
                return surface

        # 2. 降级尝试 assets/cards/<card_id>.png
        card_img_path = self.asset_root / "cards" / f"{card_id}.png"
        if card_img_path.exists():
            surface = pygame.image.load(str(card_img_path)).convert_alpha()
            surface = pygame.transform.smoothscale(surface, self.CARD_SIZE)
            self.images[key] = surface
            return surface

        # 3. 尝试 assets/images/borders/bg_<faction>.jpg / .png
        faction_key = self._normalize_faction_key(faction)
        bg_surface = self._load_faction_bg(faction_key)
        if bg_surface is not None:
            self.images[key] = bg_surface
            return bg_surface

        # 4. 降级为纯色占位
        surface = self._build_card_placeholder(str(card_id), faction)
        self.images[key] = surface
        return surface

    def get_card_back(self) -> pygame.Surface:
        """获取卡牌背面 Surface（统一给对手手牌使用）。"""
        if self._card_back is not None:
            return self._card_back

        # 文件名带空格/括号，需要精确匹配
        border_dir = self.asset_root / "images"
        candidates = [
            border_dir / "card_back(1).jpg",
            border_dir / "card_back.jpg",
            border_dir / "card_back.png",
        ]
        for path in candidates:
            if path.exists():
                surf = pygame.image.load(str(path)).convert_alpha()
                surf = pygame.transform.smoothscale(surf, self.CARD_SIZE)
                self._card_back = surf
                return surf

        # 降级：深灰色纯色背面
        surf = pygame.Surface(self.CARD_SIZE, pygame.SRCALPHA)
        surf.fill((55, 65, 80))
        pygame.draw.rect(surf, (100, 110, 130), surf.get_rect(), width=2)
        # 绘制简单花纹
        for i in range(4, self.CARD_SIZE[0] - 4, 8):
            pygame.draw.line(surf, (70, 80, 100), (i, 4), (4, i), 1)
        self._card_back = surf
        return surf

    def get_card_back_anim(self) -> pygame.Surface:
        """获取卡背动画专用 Surface（固定 80x120，缓存复用）。"""
        if self._card_back_anim is not None:
            return self._card_back_anim
        raw = self.get_card_back()
        if (raw.get_width(), raw.get_height()) != self.CARD_SIZE:
            self._card_back_anim = pygame.transform.smoothscale(raw, self.CARD_SIZE)
        else:
            self._card_back_anim = raw
        return self._card_back_anim

    def get_stat_badge(self, badge_key: str, size: tuple[int, int]) -> pygame.Surface:
        """获取数值底图（精力/攻击/限制符），懒加载 + 缓存 + 按需缩放。

        Args:
            badge_key: 'energy' | 'atk' | 'limit'
            size: 目标尺寸 (w, h)，会缩放到该大小
        Returns:
            缩放后的 Surface，文件不存在时返回蓝色/红色/灰色纯色圆形兜底
        """
        cache_key = f"{badge_key}::{size[0]}x{size[1]}"
        cached = self._stat_badges.get(cache_key)
        if cached is not None:
            return cached

        # 原图路径映射
        file_map = {
            "energy": "images/borders/bg_energy.png",
            "atk": "images/borders/bg_atk.png",
            "limit": "images/borders/bg_limit.png",
        }
        fallback_colors = {
            "energy": (60, 120, 220),
            "atk": (210, 70, 70),
            "limit": (180, 100, 40),
        }

        src_path = self.asset_root / file_map.get(badge_key, "")
        if src_path.exists():
            raw = pygame.image.load(str(src_path)).convert_alpha()
            scaled = pygame.transform.smoothscale(raw, size)
            self._stat_badges[cache_key] = scaled
            return scaled

        # 降级：纯色圆形兜底
        surf = pygame.Surface(size, pygame.SRCALPHA)
        color = fallback_colors.get(badge_key, (90, 90, 90))
        pygame.draw.circle(surf, color, (size[0] // 2, size[1] // 2), min(size) // 2)
        self._stat_badges[cache_key] = surf
        return surf

    def get_bg_surface(self, name: str) -> pygame.Surface | None:
        """加载背景大图，name 为不带后缀的文件名，如 'bg_garden'。"""
        key = f"bg::{name}"
        cached = self.images.get(key)
        if cached is not None:
            return cached

        for ext in (".png", ".jpg", ".jpeg"):
            path = self.asset_root / "images" / f"{name}{ext}"
            if path.exists():
                surf = pygame.image.load(str(path)).convert()
                self.images[key] = surf
                return surf

        return None

    def get_font(self, size: int) -> pygame.font.Font:
        normalized_size = max(8, int(size))
        cached = self.fonts.get(normalized_size)
        if cached is not None:
            return cached
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.Font(None, normalized_size)
        self.fonts[normalized_size] = font
        return font

    # ── 内部方法 ──────────────────────────────────────────────────

    def _load_faction_bg(self, faction_key: str) -> pygame.Surface | None:
        """加载 assets/images/borders/ 下的阵营背景图并缩放到卡牌尺寸。"""
        bg_name = self._FACTION_BG_MAP.get(faction_key)
        if not bg_name:
            return None

        borders_dir = self.asset_root / "images" / "borders"
        for ext in (".jpg", ".png", ".jpeg"):
            path = borders_dir / f"{bg_name}{ext}"
            if path.exists():
                surf = pygame.image.load(str(path)).convert_alpha()
                surf = pygame.transform.smoothscale(surf, self.CARD_SIZE)
                return surf

        return None

    def _build_card_placeholder(self, card_id: str, faction: Any) -> pygame.Surface:
        color = self._FACTION_COLORS.get(self._normalize_faction_key(faction), (90, 90, 90))
        surface = pygame.Surface(self.CARD_SIZE, pygame.SRCALPHA)
        surface.fill(color)
        pygame.draw.rect(surface, (20, 20, 20), surface.get_rect(), width=2)
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.Font(None, 48)
        text_surface = font.render(card_id, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=surface.get_rect().center)
        surface.blit(text_surface, text_rect)
        return surface

    def _get_plant_image(
        self, image_file: str, card_id: int | str, faction: Any,
    ) -> pygame.Surface | None:
        """仅获取植物插图 Surface（不包含阵营背景）。

        优先使用 image_file → 降级 assets/cards/<card_id>.png。
        返回 None 表示无可用图片。
        """
        # 1. 通过 image_file 精确加载
        if image_file:
            # 支持两种路径格式：
            #   "images/plants/FA_04.png" -> assets/images/plants/FA_04.png
            #   "fu_55_caiwen.png"       -> assets/cards/fu_55_caiwen.png
            if "/" in image_file:
                card_img_path = self.asset_root / image_file
            else:
                card_img_path = self.asset_root / "cards" / image_file
            if card_img_path.exists():
                return pygame.image.load(str(card_img_path)).convert_alpha()

        # 2. 降级通过 card_id 加载
        card_img_path = self.asset_root / "cards" / f"{card_id}.png"
        if card_img_path.exists():
            return pygame.image.load(str(card_img_path)).convert_alpha()

        return None

    @staticmethod
    def _normalize_faction_key(faction: Any) -> str:
        if faction is None:
            return ""
        if hasattr(faction, "name"):
            faction = str(faction.name)
        else:
            faction = str(faction)
        faction = faction.strip()
        short_map = {
            "法": "法师",
            "法师": "法师",
            "mage": "法师",
            "射": "射手",
            "射手": "射手",
            "archer": "射手",
            "坦": "坦克",
            "坦克": "坦克",
            "tank": "坦克",
            "辅": "辅助",
            "辅助": "辅助",
            "support": "辅助",
        }
        return short_map.get(faction, faction)
