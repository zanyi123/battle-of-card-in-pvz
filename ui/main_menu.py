"""ui/main_menu.py - PVZ 植物卡牌对战主菜单界面。

提供：
  - MainMenu 类：标题 + 按钮列表 + 规则弹窗 + 确认对话框
  - run_main_menu(screen, music_manager) → tuple[str, Optional[str]]:
      返回 (action, selected_world)
      - action="start_ai" : selected_world 为选定的世界名
      - action="quit"     : selected_world 为 None

菜单音乐：assets/music/menu/123. World Map.mp3（循环播放）

背景策略：静态背景图 bg_menu.png + 纯色填充，无动态植物。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import pygame

from ui.confirm_dialog import ConfirmDialog
from ui.notification_panel import NotificationPanel
from core.player_profile import get_player_name, get_display_id

if TYPE_CHECKING:
    from core.music_manager import MusicManager


# ── 调试模式开关 ─────────────────────────────────────────────────
DEBUG_MODE: bool = True   # True: 在按钮上叠加半透明色块，方便对齐调试

# ── 颜色常量 ─────────────────────────────────────────────────────
_BTN_NORMAL   = (45, 58, 75)
_BTN_HOVER    = (72, 108, 140)
_BTN_ACTIVE   = (55, 140, 90)
_BTN_DISABLED = (55, 60, 68)
_BTN_BORDER   = (130, 150, 170)
_BTN_TXT      = (235, 240, 245)
_BTN_TXT_DIS  = (100, 105, 110)
_OVERLAY_BG   = (0, 0, 0, 180)
_POPUP_BG     = (30, 38, 50)
_POPUP_BORDER = (150, 170, 200)
_TITLE_COLOR  = (255, 240, 140)
_SUBTITLE_COLOR = (190, 210, 230)

# 调试色块（R/G/B/A），各按钮各用一色
_DBG_PVE  = (255,  60,  60, 110)   # 红
_DBG_PVP  = ( 60, 220,  60, 110)   # 绿
_DBG_ACH  = ( 60,  60, 255, 110)   # 蓝
_DBG_BOT  = (255, 200,  30, 110)   # 黄

# ── 资源路径 ─────────────────────────────────────────────────────
_IMG_ROOT   = Path("assets/images")
_MUSIC_ROOT = Path("assets/music")
_SFX_ROOT   = Path("assets/sfx")
# 菜单音乐
_MENU_MUSIC   = "menu/123. World Map.mp3"
# SFX 音效
_SFX_HOVER = "button__pushbutn.wav"   # 鼠标悬停音效
_SFX_CLICK = "menu_button.wav"        # 鼠标点击音效


@dataclass
class _Button:
    label: str
    rect: pygame.Rect
    action: str             # "confirm" / "quit" / "rules" / "guide" / "settings" / ""
    disabled: bool = False
    note: str = ""          # 附加说明（如"开发中"）
    debug_color: tuple[int, int, int, int] = field(
        default_factory=lambda: (255, 60, 60, 110)
    )
    _hover: bool = field(default=False, repr=False)



class _RulesPopup:
    """游戏规则 / 玩法介绍弹窗（增大文本框，无滚动）。"""

    RULES_TEXT = (
        "【游戏规则】\n\n"
        "1. 每回合双方各有 5 点精力（Mana）。\n"
        "2. PLAY_P1 阶段：玩家点击手牌出牌，\n"
        "   点击右侧牌库区域结束出牌。\n"
        "3. PLAY_P2 阶段：AI 自动选牌出牌。\n"
        "4. RESOLVE 阶段：双方出牌互相结算伤害。\n"
        "5. 先将对手 HP 归零者获胜。\n"
        "6. 右键点击手牌可查看卡牌详情。\n\n"
        "【此处可填写更多游戏规则文本】"
    )

    GUIDE_TEXT = (
        "【玩法介绍】\n\n"
        "1. 背景：在植物温室花房，由于植物屡次击退强敌。\n"
        "花园主人们闲来无事，想通过自己的植物对决证明自己实力。\n"
        "植物也根据自身属性拉帮结伙组成阵营，\n"
        "寻找他们心中最强花园主人。\n\n"
        "2. 阵营：54张植物分为4大阵营：\n"
        "法师(FA)、射手(SH)、坦克(TK)、辅助(FU)。\n"
        "辅助植物们能力过于隐藏，不好加入三大阵营，无克制关系。\n"
        "而三大阵营相互制约：\n"
        "法师克制射手，射手克制坦克，坦克克制法师。\n\n"
        "3. 游戏对决：花园玩家初始血量上限为10点，\n"
        "初始精力上限为5点（用于种植植物，每回合自动补充）。\n"
        "将对手血量清空即游戏胜利。\n\n"
        "4. 补牌回合：当玩家血量降至0及以下时，进入濒死状态。\n"
        "此时，玩家获得一次出牌机会以存活自己（对手不会出牌）。\n\n"
        "5. 出牌规则：每个回合只允许出现：\n"
        "  单出一张任意阵营卡牌；\n"
        "  或一张三大阵营（无限制牌）加一张辅助（无限制牌）。\n"
        "精力消耗不超过当前精力现有值。\n\n"
        "6. 限制牌：在卡牌左下角查看，\n"
        "决定了卡牌是否形单影只出牌。\n\n"
        "7. 更多机制介绍，敬请探索！"
    )

    def __init__(self, screen_w: int, screen_h: int, font_getter: Any,
                 title: str = "游戏规则", body: str = "") -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.font_getter = font_getter
        self.title = title
        self.body = body or self.RULES_TEXT
        self.visible = False

        # 增大弹窗尺寸：580 x 520
        pop_w, pop_h = 580, 520
        self.rect = pygame.Rect(
            (screen_w - pop_w) // 2,
            (screen_h - pop_h) // 2,
            pop_w, pop_h,
        )

        self._title_h: int = 48
        self._btn_margin: int = 16
        btn_w, btn_h = 140, 40
        self.close_btn = pygame.Rect(
            self.rect.centerx - btn_w // 2,
            self.rect.bottom - btn_h - self._btn_margin,
            btn_w, btn_h,
        )
        self._close_hover = False

    def show(self, title: str = "", body: str = "") -> None:
        if title:
            self.title = title
        if body:
            self.body = body
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def handle_event(self, event: pygame.event.Event) -> None:
        if not self.visible:
            return
        if event.type == pygame.MOUSEMOTION:
            self._close_hover = self.close_btn.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_btn.collidepoint(event.pos):
                self.hide()

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return

        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill(_OVERLAY_BG)
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, _POPUP_BG, self.rect, border_radius=12)
        pygame.draw.rect(surface, _POPUP_BORDER, self.rect, width=2, border_radius=12)

        # 标题
        tf = self.font_getter(22, bold=True)
        ts = tf.render(self.title, True, _TITLE_COLOR)
        surface.blit(ts, ts.get_rect(centerx=self.rect.centerx, y=self.rect.y + 12))

        pygame.draw.line(
            surface, _POPUP_BORDER,
            (self.rect.x + 16, self.rect.y + self._title_h),
            (self.rect.right - 16, self.rect.y + self._title_h), 1,
        )

        # 正文区域（增大后自然容纳更多内容）
        text_area = pygame.Rect(
            self.rect.x + 20,
            self.rect.y + self._title_h + 8,
            self.rect.width - 40,
            self.close_btn.y - (self.rect.y + self._title_h + 8) - 8,
        )
        body_font = self.font_getter(15)
        self._draw_wrapped(surface, self.body, body_font, text_area, (220, 225, 235))

        # 关闭按钮
        btn_color = _BTN_HOVER if self._close_hover else _BTN_ACTIVE
        pygame.draw.rect(surface, btn_color, self.close_btn, border_radius=8)
        pygame.draw.rect(surface, _BTN_BORDER, self.close_btn, width=1, border_radius=8)
        bf = self.font_getter(16)
        bs = bf.render("我知道了", True, _BTN_TXT)
        surface.blit(bs, bs.get_rect(center=self.close_btn.center))

    @staticmethod
    def _draw_wrapped(
        surface: pygame.Surface,
        text: str,
        font: pygame.font.Font,
        area: pygame.Rect,
        color: tuple[int, int, int],
    ) -> None:
        line_h = font.get_height() + 3
        y = area.y
        for para in text.split("\n"):
            if y + line_h > area.bottom:
                break
            if para == "":
                y += line_h // 2
                continue
            cur = ""
            for ch in para:
                trial = cur + ch
                if font.size(trial)[0] <= area.width:
                    cur = trial
                else:
                    if cur:
                        s = font.render(cur, True, color)
                        surface.blit(s, (area.x, y))
                        y += line_h
                        if y + line_h > area.bottom:
                            return
                    cur = ch
            if cur:
                s = font.render(cur, True, color)
                surface.blit(s, (area.x, y))
                y += line_h

class MainMenu:
    """PVZ 卡牌对战主菜单。

    用法::

        menu = MainMenu(screen, music_manager)
        action, world = menu.run()
    """

    # ── 按钮尺寸（1024x768 基准，缩小 30%）─────────────────────
    # 左侧植物区按钮：120x42
    _SIDE_BTN_W: int = 120
    _SIDE_BTN_H: int = 42

    # 右下2x2矩阵按钮：110x38
    _BOT_BTN_W: int = 110
    _BOT_BTN_H: int = 38
    _BOT_GAP:   int = 8    # 矩阵内按钮间距（像素）

    def __init__(
        self,
        screen: pygame.Surface,
        music_manager: Optional["MusicManager"] = None,
        settings: Optional[dict[str, Any]] = None,
    ) -> None:
        self.screen = screen
        self.screen_w, self.screen_h = screen.get_size()
        self.music_manager = music_manager
        self._settings: dict[str, Any] = settings or {}

        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self._cjk_font_path = Path("assets/fonts/SourceHanSansSC-Regular.otf")
        self._buttons: list[_Button] = self._build_buttons()
        # ── 玩家信息框（右上角）
        self._profile_name = get_player_name()
        self._profile_id = get_display_id()

        self._popup = _RulesPopup(self.screen_w, self.screen_h, self.get_font)
        self._confirm_dialog = ConfirmDialog(
            screen=screen,
            screen_size=(self.screen_w, self.screen_h),
            on_confirm=self._on_confirm,
        )
        self._notif_panel = NotificationPanel(
            screen=screen,
            screen_size=(self.screen_w, self.screen_h),
            font_getter=self.get_font,
        )
        self._clock = pygame.time.Clock()
        self._selected_world: Optional[str] = None

        # ── SFX 音效预加载 ───────────────────────────────────────
        self._sfx_hover:  pygame.mixer.Sound | None = None
        self._sfx_click:  pygame.mixer.Sound | None = None
        self._load_sfx()

        # ── 静态背景图 ─────────────────────────────────────────────
        self._bg_image: pygame.Surface | None = None
        self._load_background()

        # 播放菜单音乐
        self._play_menu_music()

    # ── 菜单音乐 ─────────────────────────────────────────────────

    def _play_menu_music(self) -> None:
        """加载并循环播放菜单背景音乐，应用 BGM 音量设置。"""
        music_path = _MUSIC_ROOT / _MENU_MUSIC
        if music_path.exists():
            try:
                pygame.mixer.music.load(str(music_path))
                # 应用 BGM 音量 / 静音设置
                if self._settings.get("bgm_muted", False):
                    pygame.mixer.music.set_volume(0)
                else:
                    pygame.mixer.music.set_volume(float(self._settings.get("bgm_volume", 0.5)))
                pygame.mixer.music.play(-1)   # -1 = 无限循环
            except pygame.error:
                pass

    def _load_sfx(self) -> None:
        """预加载 SFX 音效文件。"""
        sfx_vol = float(self._settings.get("sfx_volume", 0.7))
        try:
            hover_path = _SFX_ROOT / _SFX_HOVER
            if hover_path.exists():
                self._sfx_hover = pygame.mixer.Sound(str(hover_path))
                self._sfx_hover.set_volume(sfx_vol)
        except pygame.error:
            self._sfx_hover = None
        try:
            click_path = _SFX_ROOT / _SFX_CLICK
            if click_path.exists():
                self._sfx_click = pygame.mixer.Sound(str(click_path))
                self._sfx_click.set_volume(sfx_vol)
        except pygame.error:
            self._sfx_click = None

    def _play_hover_sfx(self) -> None:
        """播放鼠标悬停音效（仅一次，避免连响）。"""
        if self._sfx_hover is not None:
            self._sfx_hover.play()

    def _play_click_sfx(self) -> None:
        """播放鼠标点击音效。"""
        if self._sfx_click is not None:
            self._sfx_click.play()

    def _load_background(self) -> None:
        """加载静态背景图 bg_menu.png。"""
        bg_path = _IMG_ROOT / "bg_menu.png"
        if bg_path.exists():
            try:
                original = pygame.image.load(str(bg_path)).convert()
                self._bg_image = pygame.transform.smoothscale(
                    original, (self.screen_w, self.screen_h)
                )
            except pygame.error:
                self._bg_image = None
        else:
            self._bg_image = None

    # ── 公共接口 ─────────────────────────────────────────────────

    def run(self) -> tuple[str, Optional[str]]:
        """阻塞运行主菜单，返回 (action, selected_world)。"""
        while True:
            dt = self._clock.tick(60) / 1000.0
            mouse_pos = pygame.mouse.get_pos()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ("quit", None)

                # 通知面板优先（最高层）
                if self._notif_panel.visible:
                    self._notif_panel.handle_event(event)
                    continue

                # 确认对话框优先
                if self._confirm_dialog.visible:
                    self._confirm_dialog.handle_event(event)
                    if not self._confirm_dialog.visible:
                        confirmed, world = self._confirm_dialog.result
                        if confirmed and world:
                            return ("start_ai", world)
                    continue

                # 弹窗
                self._popup.handle_event(event)

                if (
                    not self._popup.visible
                    and not self._notif_panel.visible
                    and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1
                ):
                    action = self._handle_click(event.pos)
                    self._play_click_sfx()   # 点击触发音效
                    if action == "confirm":
                        self._trigger_confirm_dialog()
                    elif action == "quit":
                        return ("quit", None)
                    elif action == "settings":
                        return ("settings", None)
                    elif action == "online":
                        return ("online", None)

            if self._confirm_dialog.visible:
                self._confirm_dialog.update(dt)

            if not self._popup.visible and not self._confirm_dialog.visible and not self._notif_panel.visible:
                for btn in self._buttons:
                    hit = (not btn.disabled) and btn.rect.collidepoint(mouse_pos)
                    # 悬停瞬间触发一次音效（从 False→True）
                    if hit and not btn._hover:
                        self._play_hover_sfx()
                    btn._hover = hit

            self._draw()
            pygame.display.flip()

    # ── 确认对话框 ───────────────────────────────────────────────

    def _trigger_confirm_dialog(self) -> None:
        if self.music_manager is not None:
            try:
                world = self.music_manager.pick_random_world()
                self._confirm_dialog.show(world)
                self.music_manager.play_pre(world)
                self._selected_world = world
            except RuntimeError:
                self._confirm_dialog.show("未知世界")
        else:
            self._confirm_dialog.show("测试世界")

    def _on_confirm(self, world_name: str) -> None:
        if self.music_manager is not None and world_name:
            self.music_manager.play_game(world_name)

    # ── 构建按钮（锚定植物茎部）────────────────────────────────

    def _build_buttons(self) -> list[_Button]:
        """根据 bg_menu.png（1024x768）四植物位置精准构建按钮。

        坐标策略：使用相对百分比，兼容非标准分辨率。

        背景图植物茎部估算（1024x768 基准）：
          豌豆射手 茎部约 x≈85,  y≈380   → 按钮贴茎偏右下
          大嘴花   茎部约 x≈160, y≈490   → 按钮贴大嘴花右侧
          向日葵   茎部约 x≈80,  y≈590   → 按钮贴茎偏右
          窝瓜正下方 约 x≈660, y≈690    → 2x2 矩阵
        """
        sw, sh = self.screen_w, self.screen_h
        bw, bh = self._SIDE_BTN_W, self._SIDE_BTN_H
        buttons: list[_Button] = []

        # ──────────────────────────────────────────────────────────
        # 1. 人机对战 (PvE) — 豌豆射手茎部偏右下，不遮头部
        #    茎部基准: (sw*0.083, sh*0.495)
        #    按钮左上角从茎部偏移 (+0, -bh/2)，贴茎居中
        # ──────────────────────────────────────────────────────────
        pve_x = int(sw * 0.083)
        pve_y = int(sh * 0.495) - bh // 2
        pve_rect = pygame.Rect(pve_x, pve_y, bw, bh)
        buttons.append(_Button(
            label="人机对战",
            rect=pve_rect,
            action="confirm",
            debug_color=_DBG_PVE,
        ))

        # ──────────────────────────────────────────────────────────
        # 2. 二人对战 (PvP) — 大嘴花右侧，垂直居中于茎部
        #    茎部基准: (sw*0.156, sh*0.638)
        #    按钮贴茎右侧，x 从茎部往右偏 30px
        # ──────────────────────────────────────────────────────────
        pvp_x = int(sw * 0.156) + 30
        pvp_y = int(sh * 0.638) - bh // 2
        pvp_rect = pygame.Rect(pvp_x, pvp_y, bw, bh)
        buttons.append(_Button(
            label="二人对战",
            rect=pvp_rect,
            action="online",
            disabled=False,
            note="",
            debug_color=_DBG_PVP,
        ))

        # ──────────────────────────────────────────────────────────
        # 3. 成就框 (Achievement) — 向日葵茎部偏右，左下角
        #    茎部基准: (sw*0.079, sh*0.768)
        # ──────────────────────────────────────────────────────────
        ach_x = int(sw * 0.079)
        ach_y = int(sh * 0.768) - bh // 2
        # 确保不超出屏幕底部
        ach_y = min(ach_y, sh - bh - 8)
        ach_rect = pygame.Rect(ach_x, ach_y, bw, bh)
        buttons.append(_Button(
            label="成就框",
            rect=ach_rect,
            action="achievement",
            disabled=False,
            debug_color=_DBG_ACH,
        ))

        # ──────────────────────────────────────────────────────────
        # 4. 右下角 2x2 矩阵（窝瓜正下方）
        #    矩阵基准：整体居中于 x≈[sw*0.645, sw*0.975]
        #    底部贴屏幕底 (sh - 10)
        #    矩阵总高 = 2*bh + gap，总宽 = 2*bw + gap
        # ──────────────────────────────────────────────────────────
        bbw, bbh = self._BOT_BTN_W, self._BOT_BTN_H
        gap = self._BOT_GAP

        matrix_total_w = 2 * bbw + gap
        matrix_total_h = 2 * bbh + gap

        # 矩阵水平中心约在 sw*0.81（窝瓜中轴）
        matrix_cx = int(sw * 0.81)
        matrix_x = matrix_cx - matrix_total_w // 2

        # 矩阵底部贴屏幕底部 -10px
        matrix_bottom = sh - 10
        matrix_y = matrix_bottom - matrix_total_h

        # 确保不超出屏幕
        matrix_y = max(matrix_y, sh - matrix_total_h - 12)

        # 第一行
        r0c0 = pygame.Rect(matrix_x,           matrix_y,           bbw, bbh)  # 设置
        r0c1 = pygame.Rect(matrix_x + bbw + gap, matrix_y,          bbw, bbh)  # 玩前须知
        # 第二行
        r1c0 = pygame.Rect(matrix_x,           matrix_y + bbh + gap, bbw, bbh)  # 玩法介绍
        r1c1 = pygame.Rect(matrix_x + bbw + gap, matrix_y + bbh + gap, bbw, bbh)  # 退出游戏

        bot_btns: list[tuple[str, str, str, bool]] = [
            ("设置",    "settings", "",       False),
            ("玩前须知", "rules",    "",       False),
            ("玩法介绍", "guide",    "",       False),
            ("退出游戏", "quit",     "",       False),
        ]
        bot_rects = [r0c0, r0c1, r1c0, r1c1]

        for (label, action, note, disabled), rect in zip(bot_btns, bot_rects):
            buttons.append(_Button(
                label=label,
                rect=rect,
                action=action,
                disabled=disabled,
                note=note,
                debug_color=_DBG_BOT,
            ))

        return buttons

    # ── 事件处理 ─────────────────────────────────────────────────

    def _handle_click(self, pos: tuple[int, int]) -> str:
        for btn in self._buttons:
            if btn.disabled or not btn.rect.collidepoint(pos):
                continue
            if btn.action == "rules":
                self._notif_panel.show()
                return ""
            if btn.action == "guide":
                self._popup.show(
                    title="玩法介绍",
                    body=_RulesPopup.GUIDE_TEXT,
                )
                return ""
            if btn.action in ("achievement", "settings"):
                if btn.action == "achievement":
                    self._show_achievement_popup()
                    return ""
                if btn.action == "online":
                    return "online"
                # settings action 返回给外层处理
                return btn.action
            return btn.action
        return ""

    # ── 绘制 ─────────────────────────────────────────────────────

    def _draw(self) -> None:
        """【主菜单渲染】

        层级顺序：
          Step 1: 静态背景图（bg_menu.png）
          Step 2: 调试色块（按钮边界）
          Step 3: 标题 + 按钮
          Step 4: 弹窗 + 确认对话框
        """
        # ── Step 1: 静态背景 ───────────────────────────────────────
        if self._bg_image is not None:
            self.screen.blit(self._bg_image, (0, 0))
        else:
            self.screen.fill((26, 43, 58))   # 后备纯色

        # ── Step 2: 调试色块（按钮边界）─────────────────────────────
        if DEBUG_MODE:
            self._draw_debug_overlay()

        # ── Step 3: 标题 + 按钮 + 玩家信息 ────────────────────────────
        self._draw_title()
        self._draw_player_info()
        for btn in self._buttons:
            self._draw_button(btn)

        # 版本号
        ver_font = self.get_font(12)
        ver_surf = ver_font.render(
            "v1.0 release  |  PVZ Plant Card Game", True, (100, 110, 125)
        )
        self.screen.blit(
            ver_surf,
            (self.screen_w - ver_surf.get_width() - 10, self.screen_h - 18),
        )

        # ── Step 4: 弹窗层 ──────────────────────────────────────────
        self._popup.draw(self.screen)

        # 通知面板（最顶层）
        self._notif_panel.draw()

        # 确认对话框（最顶层）
        self._confirm_dialog.draw()

    def _draw_debug_overlay(self) -> None:
        """绘制调试半透明色块 + 白色边框。"""
        for btn in self._buttons:
            dbg = pygame.Surface((btn.rect.width, btn.rect.height), pygame.SRCALPHA)
            dbg.fill(btn.debug_color)
            self.screen.blit(dbg, btn.rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255), btn.rect, width=1)

    def _show_achievement_popup(self) -> None:
        """加载存档并显示成就列表弹窗。"""
        try:
            from core.save_manager import (
                load_save_data,
                ACHIEVEMENT_NAMES,
                ACHIEVEMENT_DESCRIPTIONS,
            )
            save_data = load_save_data()
            ach = save_data.get("achievements", {})
            stats = save_data.get("stats", {})
            used_count = len(stats.get("used_card_ids", []))

            lines: list[str] = ["【成就列表】\n"]
            for ach_id, name in ACHIEVEMENT_NAMES.items():
                unlocked = ach.get(ach_id, False)
                desc = ACHIEVEMENT_DESCRIPTIONS.get(ach_id, "")
                status = "✅ 已解锁" if unlocked else "🔒 未解锁"
                lines.append(f"{name}  {status}")
                lines.append(f"   {desc}\n")

            lines.append(f"─────────────\n")
            lines.append(f"累计使用卡牌种类: {used_count}/54\n")
            lines.append(f"解锁进度: {sum(1 for v in ach.values() if v)}/{len(ACHIEVEMENT_NAMES)}")

            self._popup.show(
                title="🏆 成就",
                body="".join(lines),
            )
        except Exception as exc:
            self._popup.show(
                title="🏆 成就",
                body=f"加载成就数据失败: {exc}",
            )

    def _draw_player_info(self) -> None:
        """在菜单右上角绘制玩家信息框（名字 + ID）。"""
        if not self._profile_name:
            return

        # 信息框尺寸和位置（右上角）
        box_w, box_h = 200, 52
        box_x = self.screen_w - box_w - 12
        box_y = 10
        box_rect = pygame.Rect(box_x, box_y, box_w, box_h)

        # 半透明深色背景
        bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg_surf.fill((20, 30, 45, 200))
        self.screen.blit(bg_surf, (box_x, box_y))
        pygame.draw.rect(self.screen, (80, 100, 130), box_rect, width=1, border_radius=6)

        # 玩家名字（左对齐）
        name_font = self.get_font(16, bold=True)
        name_surf = name_font.render(self._profile_name, True, (255, 240, 140))
        self.screen.blit(name_surf, (box_x + 10, box_y + 6))

        # 玩家 ID（缩小显示）
        id_font = self.get_font(12)
        id_surf = id_font.render(f"ID: {self._profile_id}", True, (140, 155, 175))
        self.screen.blit(id_surf, (box_x + 10, box_y + 30))

    def _draw_title(self) -> None:
        title_font = self.get_font(42, bold=True)
        sub_font   = self.get_font(18)

        title_surf = title_font.render("PVZ 植物卡牌对战", True, _TITLE_COLOR)
        sub_surf   = sub_font.render(
            "Plants vs. Zombies  Card Battle", True, _SUBTITLE_COLOR
        )

        title_rect = title_surf.get_rect(centerx=self.screen_w // 2, y=55)
        sub_rect   = sub_surf.get_rect(centerx=self.screen_w // 2, y=title_rect.bottom + 8)

        shadow = title_font.render("PVZ 植物卡牌对战", True, (0, 0, 0))
        self.screen.blit(shadow, (title_rect.x + 2, title_rect.y + 2))
        self.screen.blit(title_surf, title_rect)
        self.screen.blit(sub_surf, sub_rect)

    def _draw_button(self, btn: _Button) -> None:
        if btn.disabled:
            bg_col = _BTN_DISABLED
            txt_col = _BTN_TXT_DIS
            bd_col = (80, 85, 92)
        elif btn._hover:
            bg_col = _BTN_HOVER
            txt_col = _BTN_TXT
            bd_col = (180, 200, 220)
        else:
            bg_col = _BTN_NORMAL
            txt_col = _BTN_TXT
            bd_col = _BTN_BORDER

        draw_rect = btn.rect.inflate(-4, -4) if (btn._hover and not btn.disabled) else btn.rect

        pygame.draw.rect(self.screen, bg_col, draw_rect, border_radius=8)
        pygame.draw.rect(self.screen, bd_col, draw_rect, width=2, border_radius=8)

        # 字体大小：侧边按钮 16，底部矩阵 14
        fsize = 14 if btn.rect.width <= self._BOT_BTN_W else 16
        lbl = self.get_font(fsize).render(btn.label, True, txt_col)
        self.screen.blit(lbl, lbl.get_rect(center=draw_rect.center))

        if btn.note:
            note_surf = self.get_font(11).render(btn.note, True, (140, 130, 110))
            self.screen.blit(
                note_surf,
                (btn.rect.right + 6, btn.rect.centery - note_surf.get_height() // 2),
            )

        # 玩前须知未读红点
        if btn.action == "rules" and not btn.disabled:
            unread = self._notif_panel.get_unread_count()
            if unread > 0:
                dot_x = btn.rect.right - 4
                dot_y = btn.rect.y + 4
                pygame.draw.circle(self.screen, (220, 55, 55), (dot_x, dot_y), 6)
                pygame.draw.circle(self.screen, (255, 255, 255), (dot_x, dot_y), 6, 1)
                # 数字
                nf = self.get_font(9, bold=True)
                ns = nf.render(str(min(unread, 99)), True, (255, 255, 255))
                self.screen.blit(ns, ns.get_rect(center=(dot_x, dot_y)))

    # ── 字体 ─────────────────────────────────────────────────────

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


def run_main_menu(
    screen: pygame.Surface,
    music_manager: Optional["MusicManager"] = None,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[str, Optional[str]]:
    """便捷入口：创建 MainMenu 并阻塞运行。

    Args:
        screen:        pygame 屏幕 surface
        music_manager: 可选音乐管理器
        settings:      可选设置字典（用于 BGM 音量同步）

    Returns:
        (action, selected_world)
        action 可能为 "start_ai" / "quit" / "settings"
    """
    menu = MainMenu(screen, music_manager, settings)
    return menu.run()
