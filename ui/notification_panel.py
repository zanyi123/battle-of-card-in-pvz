"""ui/notification_panel.py - 玩前须知通知系统（邮箱式界面）。

提供：
  - NotificationPanel 类：邮箱风格通知浏览界面
  - 左侧通知列表 + 右侧详情区
  - 支持未读标记、置顶排序、自动标记已读
  - 滚轮/拖拽浏览长内容

数据持久化：已读状态保存至 settings.json 的 "notifications_read" 字段。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pygame


# ── 颜色常量 ─────────────────────────────────────────────────────
_BG_OVERLAY    = (0, 0, 0, 180)
_PANEL_BG      = (25, 33, 48)
_PANEL_BORDER  = (120, 140, 170)
_LIST_BG       = (30, 40, 56)
_DETAIL_BG     = (35, 45, 62)
_ITEM_NORMAL   = (40, 52, 70)
_ITEM_HOVER    = (55, 72, 98)
_ITEM_SELECTED = (50, 68, 95)
_TITLE_COLOR   = (255, 240, 140)
_TEXT_COLOR    = (210, 218, 230)
_TEXT_DIM      = (110, 118, 130)
_TEXT_READ     = (100, 108, 120)
_RED_DOT       = (220, 55, 55)
_PIN_BADGE     = (255, 180, 50)
_BTN_GREEN     = (46, 139, 87)
_BTN_GREEN_H   = (60, 165, 105)
_BTN_GRAY      = (80, 90, 108)
_BTN_GRAY_H    = (100, 112, 132)
_SEP_COLOR     = (60, 75, 95)
_SCROLLBAR_BG  = (45, 55, 72)
_SCROLLBAR_FG  = (90, 110, 140)
_SCROLLBAR_HOV = (120, 140, 170)
_BACK_BTN_COL  = (55, 70, 92)
_BACK_BTN_HOV  = (75, 95, 125)


# ── 通知数据 ─────────────────────────────────────────────────────
NOTIFICATIONS: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": " 版权声明与使用限制",
        "content": (
            "【版权声明】\n\n"
            "本游戏为《Plants vs. Zombies》（植物大战僵尸）同人作品。\n\n"
            "【版权归属】\n\n"
            "  · 《Plants vs. Zombies》及其所有角色、美术素材、"
            "音乐等知识产权归 Electronic Arts (EA) 和 PopCap Games 所有。\n"
            "  · 本项目的代码为本人的学习实践成果，但使用的 PVZ2 素材"
            "版权归原作者所有。\n\n"
            "【项目性质】\n\n"
            "  · 本项目为非官方、非商业的个人学习项目。\n"
            "  · 仅用于编程学习和技术研究，绝不用于商业用途。\n\n"
            "【使用限制】\n\n"
            "   禁止二次传播：请勿将本游戏上传至网络或分享给他人。\n"
            "   禁止商业使用：严禁用于任何形式的盈利或商业活动。\n"
            "   仅限个人学习：仅供本人学习使用，请勿扩散。\n\n"
            "【免责声明】\n\n"
            "  · 如因使用本游戏产生任何版权纠纷，本人不承担任何法律责任。\n"
            "  · 人话说：下载游戏玩可以，线下给身边人玩可以，但是不要把游戏给别人下来传播。\n"
            "有法律风险的！！！！！\n"
            "【侵权处理】\n\n"
            "  如版权方（EA/PopCap）认为本项目侵犯您的权益， 请联系：2153816206@qq.com\n"
            "  本人将在收到通知后立即删除相关内容。\n\n"
            
            "继续游戏即表示您已阅读并同意以上条款。"
        ),
        "is_read": False,
        "is_pinned": True,
        "date": "2026-04-27",
    },
    {
        "id": 2,
        "title": "正式服版本更新说明",
        "content": (
            "【v1.1 alpha 更新内容】\n\n"
            "新增功能：\n"
            "  · 新增了22位新伙伴植物卡牌进入家族！\n"
            "  . 高级坦克：高坚果参与对战，神力钢地刺护你周全。。。。。"
            "  . 测试版本的二人对战联机已打开，有兴趣的花园玩家可以尝试一下！\n"
            ""
            "感谢您的支持与反馈！"
        ),
        "is_read": False,
        "is_pinned": False,
        "date": "2026-05-02",
    },
    {
        "id": 3,
        "title": "📜 游戏规则速览",
        "content": (
            "【游戏规则速览】\n\n"
            "基本流程：\n"
            "  1. 每回合双方初始各有 5 点阳光（Mana）,并在每个回合结束后自动补充\n"
            "  2. 点击手牌出牌，点击牌库区域结束出牌\n"
            "  3. AI 自动选牌出牌\n"
            "  4. 双方出牌互相结算伤害\n"
            "  5. 先将对手 HP 归零者获胜\n\n"
            "出牌规则：\n"
            "  · 单出任意 1 张卡牌 → 合法\n"
            "  · 2张组合：必须 1主(射/法/坦) + 1辅(辅)\n"
            "  · 两张主卡 / 两张辅卡 → 不合法\n"
            "  · 带🔒标记的卡牌不可与其他卡组合出牌\n\n"
            "卡牌阵营：\n"
            "  · 法师(FA) - 紫色 - 特殊效果为主\n"
            "  · 射手(SH) - 蓝色 - 稳定输出\n"
            "  · 坦克(TK) - 棕色 - 高生存\n"
            "  · 辅助(FU) - 白色 - 多类型，功能阵营\n\n"
            "卡牌属性：\n"
            "  · 费用(Cost)：打出需要消耗的精力\n"
            "  · 攻击力(ATK)：结算时造成的伤害值\n"
            "  · 技能(Effect)：特殊被动效果\n\n"
            "小提示：右键点击手牌可查看卡牌详情。"
        ),
        "is_read": False,
        "is_pinned": False,
        "date": "2026-04-27",
    },
]

# ── 已读状态文件 ─────────────────────────────────────────────────
from utils.path_utils import get_settings_path
_READ_STATE_PATH = get_settings_path()


def _load_read_state() -> set[int]:
    """从 settings.json 读取已读通知 ID 集合。"""
    try:
        if _READ_STATE_PATH.exists():
            data = json.loads(_READ_STATE_PATH.read_text(encoding="utf-8"))
            return set(data.get("notifications_read", []))
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return set()


def _save_read_state(read_ids: set[int]) -> None:
    """将已读通知 ID 保存到 settings.json。"""
    try:
        if _READ_STATE_PATH.exists():
            data = json.loads(_READ_STATE_PATH.read_text(encoding="utf-8"))
        else:
            data = {}
        data["notifications_read"] = sorted(read_ids)
        _READ_STATE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


@dataclass
class _NotificationItem:
    """单条通知的运行时数据。"""
    id: int
    title: str
    content: str
    is_read: bool = False
    is_pinned: bool = False
    date: str = ""


class NotificationPanel:
    """邮箱风格通知面板。

    布局：
      ┌──────────────────────────────────────┐
      │  标题栏：玩前须知            [×]     │
      ├────────────┬─────────────────────────┤
      │  通知列表  │     详情显示区          │
      │  (可滚动)  │     (可滚动)            │
      │            │                         │
      │            │                         │
      │            │               [标记已读] │
      ├────────────┴─────────────────────────┤
      │  底部信息栏                          │
      └──────────────────────────────────────┘

    用法::

        panel = NotificationPanel(screen, screen_size, font_getter)
        panel.show()
        while panel.visible:
            for event in pygame.event.get():
                panel.handle_event(event)
            panel.draw(screen)
            pygame.display.flip()
    """

    def __init__(
        self,
        screen: pygame.Surface,
        screen_size: tuple[int, int],
        font_getter: Any,
    ) -> None:
        self.screen = screen
        self.sw, self.sh = screen_size
        self.font_getter = font_getter
        self.visible: bool = False

        # ── 面板尺寸 ────────────────────────────────────────────
        self.panel_w: int = min(720, self.sw - 60)
        self.panel_h: int = min(520, self.sh - 80)
        self.panel_x: int = (self.sw - self.panel_w) // 2
        self.panel_y: int = (self.sh - self.panel_h) // 2
        self.panel_rect = pygame.Rect(
            self.panel_x, self.panel_y, self.panel_w, self.panel_h,
        )

        # ── 标题栏 ──────────────────────────────────────────────
        self._title_h: int = 44
        self._close_btn = pygame.Rect(
            self.panel_rect.right - 42,
            self.panel_rect.y + 8,
            34, 28,
        )
        self._close_hover: bool = False

        # ── 左侧列表区 ──────────────────────────────────────────
        self._list_w: int = 240
        self._list_x: int = self.panel_x
        self._list_y: int = self.panel_y + self._title_h
        self._list_h: int = self.panel_h - self._title_h

        # 列表项高度
        self._item_h: int = 52
        # 列表滚动
        self._list_scroll: int = 0
        self._list_max_scroll: int = 0
        self._list_dragging: bool = False
        self._list_drag_start_y: int = 0
        self._list_drag_start_scroll: int = 0

        # ── 右侧详情区 ──────────────────────────────────────────
        self._detail_x: int = self.panel_x + self._list_w
        self._detail_y: int = self.panel_y + self._title_h
        self._detail_w: int = self.panel_w - self._list_w
        self._detail_h: int = self.panel_h - self._title_h

        # 详情滚动
        self._detail_scroll: int = 0
        self._detail_content_h: int = 0
        self._detail_dragging: bool = False
        self._detail_drag_start_y: int = 0
        self._detail_drag_start_scroll: int = 0

        # ── 已读按钮（详情区底部）───────────────────────────────
        self._read_btn_h: int = 34
        self._read_btn = pygame.Rect(0, 0, 0, 0)  # draw 时动态计算
        self._read_btn_hover: bool = False

        # ── 底部信息栏 ──────────────────────────────────────────
        self._footer_h: int = 28

        # ── 通知数据 ────────────────────────────────────────────
        self._items: list[_NotificationItem] = []
        self._selected_id: Optional[int] = None
        self._hover_list_idx: int = -1

        # 滚轮累积（防止滚动太快）
        self._wheel_accum: int = 0

    # ── 公共接口 ─────────────────────────────────────────────────

    def show(self) -> None:
        """加载通知数据并显示面板。"""
        read_ids = _load_read_state()
        self._items = []
        for n in NOTIFICATIONS:
            self._items.append(_NotificationItem(
                id=n["id"],
                title=n["title"],
                content=n["content"],
                is_read=n["id"] in read_ids,
                is_pinned=n.get("is_pinned", False),
                date=n.get("date", ""),
            ))
        self._sort_items()
        self._selected_id = None
        self._list_scroll = 0
        self._detail_scroll = 0
        self.visible = True

    def hide(self) -> None:
        """隐藏面板并持久化已读状态。"""
        self._persist_read_state()
        self.visible = False

    # ── 排序 ────────────────────────────────────────────────────

    def _sort_items(self) -> None:
        """置顶优先 → 未读优先 → 日期倒序。"""
        def _sort_key(item: _NotificationItem) -> tuple[int, int, str]:
            pinned = 0 if item.is_pinned else 1
            unread = 0 if not item.is_read else 1
            return (pinned, unread, item.date)
        self._items.sort(key=_sort_key, reverse=False)

    def _persist_read_state(self) -> None:
        """保存所有已读通知的 ID。"""
        read_ids = {item.id for item in self._items if item.is_read}
        _save_read_state(read_ids)

    # ── 事件处理 ─────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if not self.visible:
            return

        if event.type == pygame.MOUSEMOTION:
            self._handle_motion(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._handle_left_down(event.pos)
            elif event.button == 4:  # 滚轮上
                self._handle_wheel(self._detail_rect().collidepoint(event.pos), -1)
            elif event.button == 5:  # 滚轮下
                self._handle_wheel(self._detail_rect().collidepoint(event.pos), 1)
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self._handle_left_up()
        elif event.type == pygame.MOUSEWHEEL:
            # 现代 pygame 滚轮事件
            mouse_pos = pygame.mouse.get_pos()
            in_detail = self._detail_rect().collidepoint(mouse_pos)
            in_list = self._list_rect().collidepoint(mouse_pos)
            if in_detail:
                self._detail_scroll += event.y * -30
                self._clamp_detail_scroll()
            elif in_list:
                self._list_scroll += event.y * -30
                self._clamp_list_scroll()

    def _handle_motion(self, pos: tuple[int, int]) -> None:
        self._close_hover = self._close_btn.collidepoint(pos)
        self._read_btn_hover = self._read_btn.collidepoint(pos)

        # 拖拽 - 详情区
        if self._detail_dragging:
            delta = self._detail_drag_start_y - pos[1]
            self._detail_scroll = self._detail_drag_start_scroll + delta
            self._clamp_detail_scroll()
        # 拖拽 - 列表区
        elif self._list_dragging:
            delta = self._list_drag_start_y - pos[1]
            self._list_scroll = self._list_drag_start_scroll + delta
            self._clamp_list_scroll()

        # 列表 hover
        list_rect = self._list_rect()
        self._hover_list_idx = -1
        if list_rect.collidepoint(pos):
            local_y = pos[1] - list_rect.y + self._list_scroll
            idx = local_y // self._item_h
            if 0 <= idx < len(self._items):
                self._hover_list_idx = idx

    def _handle_left_down(self, pos: tuple[int, int]) -> None:
        # 关闭按钮
        if self._close_btn.collidepoint(pos):
            self.hide()
            return

        # 已读按钮
        if self._read_btn_hover and self._selected_id is not None:
            self._mark_selected_read()
            return

        # 列表点击
        list_rect = self._list_rect()
        if list_rect.collidepoint(pos):
            local_y = pos[1] - list_rect.y + self._list_scroll
            idx = local_y // self._item_h
            if 0 <= idx < len(self._items):
                self._selected_id = self._items[idx].id
                self._detail_scroll = 0
                # 自动标记已读
                self._mark_selected_read()
            return

        # 详情区拖拽
        detail_rect = self._detail_rect()
        if detail_rect.collidepoint(pos):
            self._detail_dragging = True
            self._detail_drag_start_y = pos[1]
            self._detail_drag_start_scroll = self._detail_scroll
            return

        # 列表区拖拽
        if list_rect.collidepoint(pos):
            self._list_dragging = True
            self._list_drag_start_y = pos[1]
            self._list_drag_start_scroll = self._list_scroll

    def _handle_left_up(self) -> None:
        self._detail_dragging = False
        self._list_dragging = False

    def _handle_wheel(self, in_detail: bool, direction: int) -> None:
        """处理旧版滚轮事件（button 4/5）。"""
        if in_detail:
            self._detail_scroll += direction * -30
            self._clamp_detail_scroll()
        else:
            list_rect = self._list_rect()
            if list_rect.collidepoint(pygame.mouse.get_pos()):
                self._list_scroll += direction * -30
                self._clamp_list_scroll()

    def _mark_selected_read(self) -> None:
        """将选中通知标记为已读。"""
        if self._selected_id is None:
            return
        for item in self._items:
            if item.id == self._selected_id:
                if not item.is_read:
                    item.is_read = True
                    self._sort_items()
                break

    # ── 滚动钳制 ────────────────────────────────────────────────

    def _clamp_list_scroll(self) -> None:
        content_h = len(self._items) * self._item_h
        visible_h = self._list_h - self._footer_h
        max_scroll = max(0, content_h - visible_h)
        self._list_scroll = max(0, min(max_scroll, self._list_scroll))

    def _clamp_detail_scroll(self) -> None:
        visible_h = self._detail_h - self._read_btn_h - 20
        max_scroll = max(0, self._detail_content_h - visible_h)
        self._detail_scroll = max(0, min(max_scroll, self._detail_scroll))

    # ── 矩形计算 ────────────────────────────────────────────────

    def _list_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self._list_x, self._list_y,
            self._list_w, self._list_h - self._footer_h,
        )

    def _detail_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self._detail_x, self._detail_y,
            self._detail_w, self._detail_h - self._footer_h,
        )

    def _footer_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self._list_x,
            self._list_y + self._list_h - self._footer_h,
            self.panel_w, self._footer_h,
        )

    # ── 绘制 ────────────────────────────────────────────────────

    def draw(self) -> None:
        if not self.visible:
            return

        # 遮罩层
        overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
        overlay.fill(_BG_OVERLAY)
        self.screen.blit(overlay, (0, 0))

        # 主面板
        pygame.draw.rect(
            self.screen, _PANEL_BG,
            self.panel_rect, border_radius=12,
        )
        pygame.draw.rect(
            self.screen, _PANEL_BORDER,
            self.panel_rect, width=2, border_radius=12,
        )

        self._draw_title_bar()
        self._draw_list_area()
        self._draw_detail_area()
        self._draw_footer()

    def _draw_title_bar(self) -> None:
        """绘制标题栏 + 关闭按钮。"""
        # 标题背景
        title_rect = pygame.Rect(
            self.panel_x, self.panel_y,
            self.panel_w, self._title_h,
        )
        pygame.draw.rect(
            self.screen, (35, 45, 62),
            title_rect, border_radius=12,
        )
        # 裁掉下方圆角
        pygame.draw.rect(
            self.screen, (35, 45, 62),
            pygame.Rect(self.panel_x, self.panel_y + self._title_h - 12,
                        self.panel_w, 12),
        )

        # 标题文字
        tf = self.font_getter(20, bold=True)
        title_surf = tf.render("📬 玩前须知", True, _TITLE_COLOR)
        self.screen.blit(
            title_surf,
            (self.panel_x + 16, self.panel_y + 10),
        )

        # 关闭按钮
        col = (180, 60, 60) if self._close_hover else (100, 110, 125)
        pygame.draw.rect(
            self.screen, col, self._close_btn, border_radius=6,
        )
        xf = self.font_getter(16, bold=True)
        xs = xf.render("✕", True, (235, 240, 245))
        self.screen.blit(xs, xs.get_rect(center=self._close_btn.center))

        # 分隔线
        pygame.draw.line(
            self.screen, _PANEL_BORDER,
            (self.panel_x + 8, self.panel_y + self._title_h),
            (self.panel_rect.right - 8, self.panel_y + self._title_h),
            1,
        )

    def _draw_list_area(self) -> None:
        """绘制左侧通知列表。"""
        list_rect = self._list_rect()

        # 列表背景
        pygame.draw.rect(self.screen, _LIST_BG, list_rect)

        # 裁切区域
        clip = self.screen.get_clip()
        self.screen.set_clip(list_rect)

        for idx, item in enumerate(self._items):
            y = list_rect.y + idx * self._item_h - self._list_scroll

            # 跳过不可见的项
            if y + self._item_h < list_rect.y:
                continue
            if y > list_rect.bottom:
                break

            item_rect = pygame.Rect(list_rect.x, y, self._list_w, self._item_h)

            # 背景色
            is_selected = (item.id == self._selected_id)
            is_hover = (idx == self._hover_list_idx) and not is_selected
            if is_selected:
                bg = _ITEM_SELECTED
            elif is_hover:
                bg = _ITEM_HOVER
            else:
                bg = _ITEM_NORMAL
            pygame.draw.rect(self.screen, bg, item_rect)

            # 选中边框
            if is_selected:
                pygame.draw.rect(
                    self.screen, _PANEL_BORDER, item_rect, width=1,
                )

            # 底部线
            pygame.draw.line(
                self.screen, _SEP_COLOR,
                (item_rect.x + 8, item_rect.bottom - 1),
                (item_rect.right - 8, item_rect.bottom - 1),
                1,
            )

            # 红点（未读）
            if not item.is_read:
                dot_x = item_rect.x + 14
                dot_y = item_rect.centery
                pygame.draw.circle(self.screen, _RED_DOT, (dot_x, dot_y), 4)

            # 置顶标记
            if item.is_pinned:
                pin_x = item_rect.x + 10 if item.is_read else item_rect.x + 26
                pf = self.font_getter(12)
                ps = pf.render("📌", True, _PIN_BADGE)
                self.screen.blit(ps, (pin_x, item_rect.y + 4))

            # 标题文字
            text_x = item_rect.x + 30
            if item.is_pinned:
                text_x += 18
            text_color = _TEXT_COLOR if not item.is_read else _TEXT_READ
            is_bold = not item.is_read

            tf = self.font_getter(14, bold=is_bold)
            # 截断过长的标题
            max_w = item_rect.right - text_x - 12
            title_text = item.title
            while tf.size(title_text)[0] > max_w and len(title_text) > 1:
                title_text = title_text[:-1]
            if title_text != item.title:
                title_text += "…"

            ts = tf.render(title_text, True, text_color)
            self.screen.blit(ts, (text_x, item_rect.y + 6))

            # 日期
            if item.date:
                df = self.font_getter(11)
                ds = df.render(item.date, True, _TEXT_DIM)
                self.screen.blit(ds, (text_x, item_rect.y + 26))

            # 未读标签
            if not item.is_read:
                nf = self.font_getter(10, bold=True)
                ns = nf.render("NEW", True, _RED_DOT)
                self.screen.blit(ns, (item_rect.right - 38, item_rect.y + 28))

        # 取消裁切
        self.screen.set_clip(clip)

        # 滚动条
        self._draw_list_scrollbar(list_rect)

        # 分隔线
        pygame.draw.line(
            self.screen, _PANEL_BORDER,
            (list_rect.right, list_rect.y),
            (list_rect.right, list_rect.bottom),
            1,
        )

    def _draw_list_scrollbar(self, list_rect: pygame.Rect) -> None:
        """绘制列表滚动条。"""
        content_h = len(self._items) * self._item_h
        visible_h = list_rect.height
        if content_h <= visible_h:
            return

        bar_w = 6
        bar_x = list_rect.right - bar_w - 4
        bar_h = list_rect.height

        # 轨道
        pygame.draw.rect(
            self.screen, _SCROLLBAR_BG,
            pygame.Rect(bar_x, list_rect.y, bar_w, bar_h),
            border_radius=3,
        )

        # 滑块
        ratio = visible_h / content_h
        thumb_h = max(20, int(bar_h * ratio))
        scroll_range = content_h - visible_h
        if scroll_range > 0:
            thumb_y = list_rect.y + int(
                (self._list_scroll / scroll_range) * (bar_h - thumb_h)
            )
        else:
            thumb_y = list_rect.y

        mouse_pos = pygame.mouse.get_pos()
        thumb_rect = pygame.Rect(bar_x, thumb_y, bar_w, thumb_h)
        hover = thumb_rect.collidepoint(mouse_pos)
        col = _SCROLLBAR_HOV if hover else _SCROLLBAR_FG
        pygame.draw.rect(self.screen, col, thumb_rect, border_radius=3)

    def _draw_detail_area(self) -> None:
        """绘制右侧详情区。"""
        detail_rect = self._detail_rect()
        pygame.draw.rect(self.screen, _DETAIL_BG, detail_rect)

        if self._selected_id is None:
            # 占位提示
            hf = self.font_getter(18)
            hs = hf.render("← 请选择一条通知查看", True, _TEXT_DIM)
            self.screen.blit(
                hs, hs.get_rect(center=detail_rect.center),
            )
            return

        # 查找选中项
        selected_item: Optional[_NotificationItem] = None
        for item in self._items:
            if item.id == self._selected_id:
                selected_item = item
                break
        if selected_item is None:
            return

        # 详情标题
        dtf = self.font_getter(16, bold=True)
        dts = dtf.render(selected_item.title, True, _TITLE_COLOR)
        title_y = detail_rect.y + 10
        self.screen.blit(dts, (detail_rect.x + 16, title_y))

        # 分隔线
        sep_y = title_y + dts.get_height() + 8
        pygame.draw.line(
            self.screen, _SEP_COLOR,
            (detail_rect.x + 12, sep_y),
            (detail_rect.right - 12, sep_y),
            1,
        )

        # 正文内容（可滚动）
        content_top = sep_y + 8
        content_bottom = detail_rect.bottom - self._read_btn_h - 16
        content_area = pygame.Rect(
            detail_rect.x + 16, content_top,
            detail_rect.width - 32, content_bottom - content_top,
        )

        # 计算内容总高度
        self._detail_content_h = self._measure_text_height(
            selected_item.content, self.font_getter(14), content_area.width,
        )

        # 裁切 + 偏移
        clip = self.screen.get_clip()
        self.screen.set_clip(content_area)

        # 用临时 surface 渲染内容
        text_surf = self._render_text_block(
            selected_item.content, self.font_getter(14),
            content_area.width, self._detail_content_h,
        )
        self.screen.blit(text_surf, (content_area.x, content_area.y - self._detail_scroll))

        self.screen.set_clip(clip)

        # 滚动条
        self._draw_detail_scrollbar(detail_rect, content_area)

        # 已读按钮
        btn_y = detail_rect.bottom - self._read_btn_h - 8
        if selected_item.is_read:
            label = "✅ 已阅读"
            col = _BTN_GRAY
            col_h = _BTN_GRAY_H
        else:
            label = "标记为已读"
            col = _BTN_GREEN
            col_h = _BTN_GREEN_H

        btn_w = 120
        self._read_btn = pygame.Rect(
            detail_rect.right - btn_w - 16, btn_y,
            btn_w, self._read_btn_h,
        )
        btn_col = col_h if self._read_btn_hover else col
        pygame.draw.rect(
            self.screen, btn_col, self._read_btn, border_radius=6,
        )
        bf = self.font_getter(13)
        bs = bf.render(label, True, (220, 228, 238))
        self.screen.blit(bs, bs.get_rect(center=self._read_btn.center))

    def _draw_detail_scrollbar(
        self,
        detail_rect: pygame.Rect,
        content_area: pygame.Rect,
    ) -> None:
        """绘制详情区滚动条。"""
        visible_h = content_area.height
        if self._detail_content_h <= visible_h:
            return

        bar_w = 6
        bar_x = detail_rect.right - bar_w - 6
        bar_h = detail_rect.height

        pygame.draw.rect(
            self.screen, _SCROLLBAR_BG,
            pygame.Rect(bar_x, detail_rect.y, bar_w, bar_h),
            border_radius=3,
        )

        ratio = visible_h / self._detail_content_h
        thumb_h = max(20, int(bar_h * ratio))
        scroll_range = self._detail_content_h - visible_h
        if scroll_range > 0:
            thumb_y = detail_rect.y + int(
                (self._detail_scroll / scroll_range) * (bar_h - thumb_h)
            )
        else:
            thumb_y = detail_rect.y

        mouse_pos = pygame.mouse.get_pos()
        thumb_rect = pygame.Rect(bar_x, thumb_y, bar_w, thumb_h)
        hover = thumb_rect.collidepoint(mouse_pos)
        col = _SCROLLBAR_HOV if hover else _SCROLLBAR_FG
        pygame.draw.rect(self.screen, col, thumb_rect, border_radius=3)

    def _draw_footer(self) -> None:
        """绘制底部信息栏。"""
        footer_rect = self._footer_rect()

        pygame.draw.rect(self.screen, (28, 36, 50), footer_rect)
        pygame.draw.line(
            self.screen, _SEP_COLOR,
            (footer_rect.x, footer_rect.y),
            (footer_rect.right, footer_rect.y),
            1,
        )

        # 未读统计
        unread = sum(1 for item in self._items if not item.is_read)
        total = len(self._items)
        ff = self.font_getter(12)
        if unread > 0:
            text = f"📬 {unread} 条未读 / 共 {total} 条通知"
        else:
            text = f"📭 全部已读 / 共 {total} 条通知"
        fs = ff.render(text, True, _TEXT_DIM)
        self.screen.blit(fs, (footer_rect.x + 12, footer_rect.y + 6))

    # ── 文本渲染工具 ────────────────────────────────────────────

    @staticmethod
    def _measure_text_height(text: str, font: pygame.font.Font, max_w: int) -> int:
        """测量多段文本总高度。"""
        line_h = font.get_height() + 4
        total = 0
        for para in text.split("\n"):
            if para == "":
                total += line_h // 2
                continue
            cur = ""
            for ch in para:
                trial = cur + ch
                if font.size(trial)[0] <= max_w:
                    cur = trial
                else:
                    if cur:
                        total += line_h
                    cur = ch
            if cur:
                total += line_h
        return total

    @staticmethod
    def _render_text_block(
        text: str,
        font: pygame.font.Font,
        max_w: int,
        total_h: int,
    ) -> pygame.Surface:
        """将多段文本渲染到一个透明 Surface 上。"""
        line_h = font.get_height() + 4
        surf = pygame.Surface((max_w, total_h), pygame.SRCALPHA)
        y = 0
        color = (210, 218, 230)
        for para in text.split("\n"):
            if para == "":
                y += line_h // 2
                continue
            cur = ""
            for ch in para:
                trial = cur + ch
                if font.size(trial)[0] <= max_w:
                    cur = trial
                else:
                    if cur:
                        s = font.render(cur, True, color)
                        surf.blit(s, (0, y))
                        y += line_h
                    cur = ch
            if cur:
                s = font.render(cur, True, color)
                surf.blit(s, (0, y))
                y += line_h
        return surf

    # ── 外部查询 ────────────────────────────────────────────────

    def get_unread_count(self) -> int:
        """返回当前未读通知数（不加载，仅查持久化）。"""
        read_ids = _load_read_state()
        return sum(1 for n in NOTIFICATIONS if n["id"] not in read_ids)
