"""network/lobby.py - 联机大厅界面。

界面元素：
  - 标题 "联机对战大厅"
  - 局域网名称（子网标识）
  - 在线玩家列表：名字（左）、ID（中右）、邀请按钮（最右）
  - 手动输入IP连接（同电脑双开输入 127.0.0.1）
  - 底部 "返回" 按钮
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any, Optional

import pygame

from core.player_profile import get_player_id, get_player_name, get_display_id
from network.lan_discovery import LanDiscovery
from network.protocol import LAN_PORT, make_message, parse_message
from network.game_host import GameHost
from network.game_client import GameClient
from main import log_event


# ── 颜色 ─────────────────────────────────────────────────────
_BG_COLOR       = (26, 43, 58)
_PANEL_BG       = (32, 45, 62)
_PANEL_BORDER   = (70, 90, 120)
_TITLE_COLOR    = (255, 240, 140)
_SUBTITLE_CLR   = (160, 180, 200)
_LAN_LABEL_CLR  = (100, 180, 255)
_ROW_BG         = (38, 52, 72)
_ROW_HOVER      = (55, 75, 100)
_NAME_CLR       = (230, 235, 245)
_ID_CLR         = (130, 145, 165)
_BTN_INVITE     = (55, 140, 90)
_BTN_INVITE_HVR = (70, 170, 110)
_BTN_INVITE_DIS = (60, 65, 72)
_BTN_TXT        = (235, 240, 245)
_BTN_BACK       = (45, 58, 75)
_BTN_BACK_HVR   = (72, 108, 140)
_BTN_BORDER     = (130, 150, 170)
_INPUT_BG       = (245, 245, 250)
_INPUT_BORDER   = (130, 150, 170)
_INPUT_ACTIVE_C = (72, 108, 200)
_STATUS_WAIT    = "等待发现玩家..."
_STATUS_CONN    = "正在连接..."
_EMPTY_MSG      = "暂无其他玩家在线，可手动输入IP连接"


class LobbyScreen:
    """联机大厅界面。"""

    def __init__(
        self,
        screen: pygame.Surface,
        screen_size: tuple[int, int],
    ) -> None:
        self.screen = screen
        self.sw, self.sh = screen_size
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self._cjk_font_path = Path("assets/fonts/SourceHanSansSC-Regular.otf")

        # 局域网发现
        self._discovery = LanDiscovery()
        self._online_players: list[dict[str, Any]] = []

        # UI 状态
        self._hovered_invite_idx: int = -1
        self._hovered_back: bool = False
        self._status_msg: str = _STATUS_WAIT
        self._invited_player_id: str = ""
        self._waiting_response: bool = False
        self._connected: bool = False

        # ── 手动IP连接 ──────────────────────────────────────
        self._ip_input_text: str = ""
        self._ip_input_active: bool = False
        self._ip_cursor_visible: bool = True
        self._ip_cursor_timer: float = 0.0

        # 返回按钮
        bw, bh = 140, 40
        self._back_btn = pygame.Rect(20, self.sh - 60, bw, bh)

        # 面板区域（居中）
        panel_w = 640
        panel_h = 480
        self._panel_rect = pygame.Rect(
            (self.sw - panel_w) // 2, 80, panel_w, panel_h
        )

        # 列表区域（缩短，底部留空给IP输入框）
        list_margin = 16
        self._list_rect = pygame.Rect(
            self._panel_rect.x + list_margin,
            self._panel_rect.y + 110,
            self._panel_rect.width - list_margin * 2,
            self._panel_rect.height - 110 - 80,  # 底部留80px给IP输入
        )

        # ── IP输入框 + 连接按钮（面板底部）──────────────────
        ip_y = self._list_rect.bottom + 10
        self._ip_input_rect = pygame.Rect(
            self._panel_rect.x + 20, ip_y, 360, 36
        )
        self._connect_btn = pygame.Rect(
            self._ip_input_rect.right + 12, ip_y, 100, 36
        )
        self._hovered_connect: bool = False

        # 行高
        self._row_h = 48
        self._invite_btn_w = 80

        # 服务器/客户端引用（游戏启动后使用）
        self._game_host: GameHost | None = None
        self._game_client: GameClient | None = None

        # TCP 监听（被邀请时）
        self._server_sock: socket.socket | None = None
        self._listen_thread: threading.Thread | None = None
        self._client_sock: socket.socket | None = None
        self._accepting: bool = False
        self._my_listen_port: int = 0       # 本实例监听的端口，连接时跳过防止自连

        # 邀请回调结果
        self._invite_result: str = ""  # "" / "host" / "client"
        self._peer_ip: str = ""

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

    # ── 启动 / 停止 ───────────────────────────────────────────

    def start(self) -> None:
        """启动局域网发现 + TCP 监听。"""
        self._discovery.start()
        self._start_tcp_listen()

    def stop(self) -> None:
        """停止所有网络服务。"""
        self._discovery.stop()
        self._stop_tcp_listen()

    def _start_tcp_listen(self) -> None:
        """启动 TCP 监听线程，等待被邀请。

        双开兼容：
          - 不使用 SO_REUSEADDR，防止两个实例绑定同一端口导致自连。
          - 如果默认端口被占，自动尝试 +1 ~ +9 端口。
          - 每次尝试创建新 socket，避免地址复用。
        """
        self._accepting = True
        bound_port = None

        for port in range(LAN_PORT, LAN_PORT + 10):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # 不设置 SO_REUSEADDR → 第二个实例 bind 同端口会失败，
                # 从而尝试下一个端口，杜绝同一台机器双开时自连
                sock.bind(("", port))
                sock.listen(1)
                sock.settimeout(1.0)
                self._server_sock = sock
                bound_port = port
                break
            except OSError:
                try:
                    sock.close()
                except Exception:
                    pass
                continue

        if bound_port is None:
            log_event("[Lobby] TCP 端口绑定全部失败（9988-9997）", "error")
            self._accepting = False
            self._server_sock = None
            return

        self._my_listen_port = bound_port  # 记住自己的端口，连接时跳过
        self._listen_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._listen_thread.start()
        log_event(f"[Lobby] TCP 监听启动: 端口 {bound_port}")

    def _stop_tcp_listen(self) -> None:
        """停止 TCP 监听（不关闭游戏连接 socket）。"""
        self._accepting = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        # 注意：不关闭 _client_sock，GameClient/GameHost 还在用它

    # ── 网络连接 ──────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """TCP 接受连接循环（被动方 → Client 角色）。

        自连防护由端口隔离保证（不设 SO_REUSEADDR → 第二个实例绑不同端口）。
        """
        while self._accepting and not self._connected:
            try:
                if self._server_sock is None:
                    break
                conn, addr = self._server_sock.accept()
                conn.settimeout(5.0)
                # 接收邀请消息
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                parsed = parse_message(data.decode("utf-8"))
                if parsed:
                    msg_type, payload = parsed
                    if msg_type == "INVITE":
                        # 双开时两个实例共用同一 player_profile → player_id 相同
                        # 不用 player_id 判断自连，而是依赖端口隔离（不设 SO_REUSEADDR）
                        # 所以这里直接接受
                        resp = make_message("INVITE_ACCEPT", {
                            "player_id": get_player_id(),
                            "player_name": get_player_name(),
                        })
                        conn.sendall(resp.encode("utf-8"))
                        self._peer_ip = addr[0]
                        self._connected = True
                        self._client_sock = conn
                        self._invite_result = "client"
                        self._game_client = GameClient(conn)
                        return
            except socket.timeout:
                continue
            except Exception:
                continue

    def _send_invite(self, peer_ip: str, peer_id: str = "") -> None:
        """向目标IP发送邀请（主动方 → Host 角色）。

        双开兼容：依次尝试 LAN_PORT ~ LAN_PORT+9 端口连接。
        """
        if self._waiting_response or self._connected:
            return

        self._status_msg = _STATUS_CONN
        self._invited_player_id = peer_id

        def _connect():
            sock = None
            connected_port = None

            # 判断是否连接本机（双开场景）
            is_localhost = peer_ip in ("127.0.0.1", "localhost", "0.0.0.0")

            # 尝试多个端口（双开兼容）
            for port in range(LAN_PORT, LAN_PORT + 10):
                # 双开时跳过自己的监听端口，防止自连
                if is_localhost and port == self._my_listen_port:
                    continue
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(2.0)
                    s.connect((peer_ip, port))
                    sock = s
                    connected_port = port
                    break
                except (socket.timeout, ConnectionRefusedError, OSError):
                    continue

            if sock is None:
                self._status_msg = f"连接失败: 无法连接到 {peer_ip}"
                self._waiting_response = False
                return

            try:
                # 发送邀请
                invite_msg = make_message("INVITE", {
                    "player_id": get_player_id(),
                    "player_name": get_player_name(),
                })
                sock.sendall(invite_msg.encode("utf-8"))

                # 等待回复
                data = b""
                while b"\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk

                parsed = parse_message(data.decode("utf-8"))
                if parsed:
                    msg_type, payload = parsed
                    if msg_type == "INVITE_ACCEPT":
                        self._connected = True
                        self._peer_ip = peer_ip
                        self._invite_result = "host"
                        self._game_host = GameHost(sock)
                    elif msg_type == "INVITE_REJECT":
                        self._status_msg = "对方拒绝了邀请"
                        self._waiting_response = False
                        sock.close()
                else:
                    self._status_msg = "连接异常"
                    self._waiting_response = False
                    sock.close()
            except Exception as e:
                self._status_msg = f"连接失败: {e}"
                self._waiting_response = False
                try:
                    sock.close()
                except Exception:
                    pass

        self._waiting_response = True
        t = threading.Thread(target=_connect, daemon=True)
        t.start()

    # ── 事件处理 ──────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._connected:
            return

        if event.type == pygame.MOUSEMOTION:
            self._hovered_back = self._back_btn.collidepoint(event.pos)
            self._hovered_invite_idx = self._get_hovered_invite_idx(event.pos)
            self._hovered_connect = self._connect_btn.collidepoint(event.pos)
            # 点击输入框激活
            if self._ip_input_rect.collidepoint(event.pos):
                self._ip_input_active = True
            else:
                self._ip_input_active = False

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 点击连接按钮
            if self._connect_btn.collidepoint(event.pos):
                self._on_connect_click()
                return

            # 点击IP输入框
            if self._ip_input_rect.collidepoint(event.pos):
                self._ip_input_active = True
            else:
                self._ip_input_active = False

            # 点击邀请按钮
            idx = self._get_hovered_invite_idx(event.pos)
            if idx >= 0 and idx < len(self._online_players):
                player = self._online_players[idx]
                self._send_invite(player["ip"], player["player_id"])

        elif event.type == pygame.KEYDOWN and self._ip_input_active:
            if event.key == pygame.K_RETURN:
                self._on_connect_click()
            elif event.key == pygame.K_BACKSPACE:
                self._ip_input_text = self._ip_input_text[:-1]
            elif event.unicode.isprintable() and event.unicode:
                if len(self._ip_input_text) < 21:  # IPv6最长约21字符
                    self._ip_input_text += event.unicode

    def _on_connect_click(self) -> None:
        """点击"连接"按钮：向输入的IP发送邀请。"""
        ip = self._ip_input_text.strip()
        if not ip:
            self._status_msg = "请输入IP地址"
            return
        log_event(f"[Lobby] 手动连接: {ip}:{LAN_PORT}")
        self._send_invite(ip)

    def _get_hovered_invite_idx(self, pos: tuple[int, int]) -> int:
        for i, player in enumerate(self._online_players):
            btn_rect = self._get_invite_btn_rect(i)
            if btn_rect and btn_rect.collidepoint(pos):
                return i
        return -1

    def _get_invite_btn_rect(self, idx: int) -> pygame.Rect | None:
        y = self._list_rect.y + idx * self._row_h
        if y + self._row_h > self._list_rect.bottom:
            return None
        return pygame.Rect(
            self._list_rect.right - self._invite_btn_w - 8,
            y + (self._row_h - 32) // 2,
            self._invite_btn_w,
            32,
        )

    # ── 更新 ──────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """更新在线玩家列表 + 光标闪烁。"""
        self._online_players = self._discovery.get_online_players()
        if not self._waiting_response and not self._connected:
            if self._online_players:
                self._status_msg = f"已发现 {len(self._online_players)} 位玩家"
            else:
                self._status_msg = _STATUS_WAIT

        # 光标闪烁
        self._ip_cursor_timer += dt
        if self._ip_cursor_timer >= 0.5:
            self._ip_cursor_timer = 0.0
            self._ip_cursor_visible = not self._ip_cursor_visible

    # ── 绘制 ──────────────────────────────────────────────────

    def draw(self) -> None:
        """绘制大厅界面。"""
        self.screen.fill(_BG_COLOR)

        # ── 标题 ───────────────────────────────────────────────
        title_font = self.get_font(30, bold=True)
        title_surf = title_font.render("联机对战大厅", True, _TITLE_COLOR)
        self.screen.blit(title_surf, title_surf.get_rect(centerx=self.sw // 2, y=25))

        # ── 面板背景 ───────────────────────────────────────────
        pygame.draw.rect(self.screen, _PANEL_BG, self._panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, _PANEL_BORDER, self._panel_rect, width=1, border_radius=10)

        # ── 局域网名称 + 监听端口 ─────────────────────────────────
        subnet = self._discovery.get_subnet_name()
        lan_font = self.get_font(15)
        # 显示本机监听端口
        listen_port = ""
        if self._server_sock:
            try:
                listen_port = f":{self._server_sock.getsockname()[1]}"
            except Exception:
                pass
        lan_surf = lan_font.render(f"局域网: {subnet}  监听端口: {listen_port or '未启动'}", True, _LAN_LABEL_CLR)
        self.screen.blit(lan_surf, (self._panel_rect.x + 16, self._panel_rect.y + 12))

        # ── 自己信息 ───────────────────────────────────────────
        my_name = get_player_name()
        my_id = get_display_id()
        me_surf = lan_font.render(f"你: {my_name}  ID: {my_id}", True, _SUBTITLE_CLR)
        self.screen.blit(me_surf, (self._panel_rect.x + 16, self._panel_rect.y + 38))

        # ── 状态 ───────────────────────────────────────────────
        status_font = self.get_font(14)
        status_surf = status_font.render(self._status_msg, True, _SUBTITLE_CLR)
        self.screen.blit(status_surf, (self._panel_rect.x + 16, self._panel_rect.y + 62))

        # ── 分割线 ─────────────────────────────────────────────
        sep_y = self._panel_rect.y + 88
        pygame.draw.line(
            self.screen, _PANEL_BORDER,
            (self._panel_rect.x + 12, sep_y),
            (self._panel_rect.right - 12, sep_y), 1,
        )

        # ── 列表表头 ───────────────────────────────────────────
        header_font = self.get_font(13, bold=True)
        hdr_name = header_font.render("玩家名字", True, _ID_CLR)
        hdr_action = header_font.render("操作", True, _ID_CLR)
        self.screen.blit(hdr_name, (self._list_rect.x + 12, self._list_rect.y - 18))
        self.screen.blit(hdr_action, (self._list_rect.right - self._invite_btn_w - 8, self._list_rect.y - 18))

        # ── 玩家列表 ───────────────────────────────────────────
        if not self._online_players:
            empty_font = self.get_font(16)
            empty_surf = empty_font.render(_EMPTY_MSG, True, _ID_CLR)
            self.screen.blit(
                empty_surf,
                empty_surf.get_rect(center=self._list_rect.center),
            )
        else:
            self._draw_player_list()

        # ── IP输入框 + 连接按钮 ────────────────────────────────
        ip_label_font = self.get_font(13)
        ip_label = ip_label_font.render("手动连接IP:", True, _SUBTITLE_CLR)
        self.screen.blit(ip_label, (self._ip_input_rect.x, self._ip_input_rect.y - 16))

        # 输入框
        border_color = _INPUT_ACTIVE_C if self._ip_input_active else _INPUT_BORDER
        outer = self._ip_input_rect.inflate(4, 4)
        pygame.draw.rect(self.screen, border_color, outer, border_radius=6)
        pygame.draw.rect(self.screen, _INPUT_BG, self._ip_input_rect, border_radius=4)

        # 输入框文字
        ip_font = self.get_font(16)
        txt_surf = ip_font.render(self._ip_input_text, True, (30, 30, 30))
        clip = self.screen.get_clip()
        self.screen.set_clip(self._ip_input_rect)
        self.screen.blit(txt_surf, (self._ip_input_rect.x + 8, self._ip_input_rect.centery - txt_surf.get_height() // 2))
        # 光标
        if self._ip_input_active and self._ip_cursor_visible:
            cx = self._ip_input_rect.x + 8 + txt_surf.get_width() + 2
            pygame.draw.line(
                self.screen, (30, 30, 30),
                (cx, self._ip_input_rect.y + 6),
                (cx, self._ip_input_rect.bottom - 6), 2,
            )
        # 占位提示
        if not self._ip_input_text and not self._ip_input_active:
            hint_font = self.get_font(14)
            hint_surf = hint_font.render("127.0.0.1 (同电脑双开)", True, (160, 165, 175))
            self.screen.blit(hint_surf, (self._ip_input_rect.x + 8, self._ip_input_rect.centery - hint_surf.get_height() // 2))
        self.screen.set_clip(clip)

        # 连接按钮
        conn_color = _BTN_INVITE_HVR if self._hovered_connect else _BTN_INVITE
        pygame.draw.rect(self.screen, conn_color, self._connect_btn, border_radius=6)
        pygame.draw.rect(self.screen, _BTN_BORDER, self._connect_btn, width=1, border_radius=6)
        conn_font = self.get_font(15, bold=True)
        conn_surf = conn_font.render("连接", True, _BTN_TXT)
        self.screen.blit(conn_surf, conn_surf.get_rect(center=self._connect_btn.center))

        # ── 连接成功提示 ───────────────────────────────────────
        if self._connected:
            overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))
            conn_font = self.get_font(24, bold=True)
            conn_surf = conn_font.render("连接成功！正在启动游戏...", True, (100, 255, 100))
            self.screen.blit(conn_surf, conn_surf.get_rect(center=(self.sw // 2, self.sh // 2)))

        # ── 返回按钮 ───────────────────────────────────────────
        btn_color = _BTN_BACK_HVR if self._hovered_back else _BTN_BACK
        pygame.draw.rect(self.screen, btn_color, self._back_btn, border_radius=8)
        pygame.draw.rect(self.screen, _BTN_BORDER, self._back_btn, width=2, border_radius=8)
        back_font = self.get_font(16)
        back_surf = back_font.render("返回菜单", True, _BTN_TXT)
        self.screen.blit(back_surf, back_surf.get_rect(center=self._back_btn.center))

    def _draw_player_list(self) -> None:
        """绘制在线玩家列表行。"""
        name_font = self.get_font(16)
        id_font = self.get_font(13)
        btn_font = self.get_font(14, bold=True)

        for i, player in enumerate(self._online_players):
            y = self._list_rect.y + i * self._row_h
            if y + self._row_h > self._list_rect.bottom:
                break

            row_rect = pygame.Rect(self._list_rect.x, y, self._list_rect.width, self._row_h)

            is_hovered = (i == self._hovered_invite_idx)
            bg_color = _ROW_HOVER if is_hovered else _ROW_BG
            pygame.draw.rect(self.screen, bg_color, row_rect, border_radius=4)

            name_surf = name_font.render(player.get("name", "未知"), True, _NAME_CLR)
            self.screen.blit(name_surf, (row_rect.x + 16, y + (self._row_h - name_surf.get_height()) // 2))

            pid = player.get("player_id", "")[:8].upper()
            id_surf = id_font.render(f"ID: {pid}", True, _ID_CLR)
            self.screen.blit(id_surf, (row_rect.x + 260, y + (self._row_h - id_surf.get_height()) // 2))

            invite_rect = self._get_invite_btn_rect(i)
            if invite_rect:
                is_invited = player.get("player_id") == self._invited_player_id
                if self._waiting_response and is_invited:
                    btn_bg = _BTN_INVITE_DIS
                    btn_label = "等待中"
                elif is_hovered:
                    btn_bg = _BTN_INVITE_HVR
                    btn_label = "邀请"
                else:
                    btn_bg = _BTN_INVITE
                    btn_label = "邀请"

                pygame.draw.rect(self.screen, btn_bg, invite_rect, border_radius=6)
                invite_surf = btn_font.render(btn_label, True, _BTN_TXT)
                self.screen.blit(invite_surf, invite_surf.get_rect(center=invite_rect.center))

                pygame.draw.line(
                    self.screen, (50, 65, 85),
                    (row_rect.x + 8, row_rect.bottom - 1),
                    (row_rect.right - 8, row_rect.bottom - 1), 1,
                )


_last_lobby: LobbyScreen | None = None


def run_lobby(
    screen: pygame.Surface,
    screen_size: tuple[int, int],
    music_manager: Any = None,
    settings: Any = None,
) -> str:
    """运行联机大厅主循环。

    Returns:
        "back"  → 返回主菜单
        "start" → 连接成功，可以开始游戏
    """
    global _last_lobby
    lobby = LobbyScreen(screen, screen_size)
    lobby.start()
    _last_lobby = lobby
    clock = pygame.time.Clock()

    result = "back"

    while True:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                lobby.stop()
                return "back"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                lobby.stop()
                return "back"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if lobby._back_btn.collidepoint(event.pos) and not lobby._connected:
                    lobby.stop()
                    return "back"
            lobby.handle_event(event)

        lobby.update(dt)
        lobby.draw()
        pygame.display.flip()

        # 检查是否连接成功
        if lobby._connected and lobby._invite_result:
            # 短暂展示连接成功
            pygame.time.wait(1000)
            lobby.stop()
            result = "start"
            return result

    return result
