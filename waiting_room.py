"""
waiting_room.py
---------------
Side-selection waiting room shown between the main menu and the game.

Flow:
  1. Connects to the WebSocket server (same address discovered by menu).
  2. Each player picks Hero or Boss.
  3. Preferences are sent to the server which resolves conflicts randomly.
  4. Server sends back a `role_assigned` message with the final role.
  5. The resolved role is stored in DUNGEON_ARISE_ROLE env var (0=Hero, 1=Boss).
  6. taskMgr stops; control returns to main.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading

from direct.gui.DirectGui import DirectButton, DirectFrame, OnscreenText
from direct.gui import DirectGuiGlobals as DGG
from direct.showbase.ShowBase import ShowBase
from panda3d.core import TextNode, TransparencyAttrib, loadPrcFileData

import websockets

loadPrcFileData("", "win-size 1920 1080")

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
ROLE_HERO = 0
ROLE_BOSS = 1

ROLE_LABELS = {ROLE_HERO: "HERO", ROLE_BOSS: "BOSS"}
ROLE_DESCRIPTIONS = {
    ROLE_HERO: (
        "Traverse the dungeon.\n"
        "Fight through monsters.\n"
        "Reach and defeat the Boss."
    ),
    ROLE_BOSS: (
        "Shape the dungeon.\n"
        "Summon minions.\n"
        "Stop the Hero at all costs."
    ),
}
ROLE_COLORS = {
    ROLE_HERO: (0.35, 0.75, 1.0, 1.0),   # cool blue
    ROLE_BOSS: (1.0, 0.35, 0.25, 1.0),   # fiery red-orange
}


class WaitingRoom(ShowBase):
    """Side-selection lobby screen."""

    def __init__(self):
        super().__init__()
        self.disableMouse()

        # ── outcome ──────────────────────────────────────────────────────────
        self.start_requested: bool = False
        self.assigned_role: int | None = None

        # ── network state ────────────────────────────────────────────────────
        self._port = int(os.getenv("DUNGEON_ARISE_PORT", str(DEFAULT_PORT)))
        host_raw = os.getenv("DUNGEON_ARISE_HOST", DEFAULT_HOST)
        self._host = host_raw.split(":")[0]
        self._ws_uri = f"ws://{self._host}:{self._port}"

        self._my_server_role: int | None = None   # role assigned by server (0 or 1)
        self._my_pref: int | None = None           # role the player WANTS
        self._peer_connected: bool = False
        self._ws = None

        # WS runs in a background thread with its own event loop
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._ws_thread = threading.Thread(target=self._run_ws_loop, daemon=True)
        self._ws_thread.start()

        # ── colours ──────────────────────────────────────────────────────────
        self._blue_glow = (0.45, 0.85, 1.0, 0.9)
        self._soft_white = (1.0, 1.0, 1.0, 0.9)
        self._dim_white  = (0.55, 0.55, 0.6, 0.8)

        self._build_ui()

        self.taskMgr.add(self._task_update,    "wr_update")
        self.taskMgr.add(self._mouse_parallax, "wr_parallax")

    # ──────────────────────────────────────── network ────────────────────────

    def _run_ws_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _schedule(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _ws_handler(self):
        """Connect, wait for welcome, exchange prefs, wait for role_assigned."""
        try:
            async with websockets.connect(self._ws_uri) as ws:
                self._ws = ws

                # First message is always the welcome from the server
                raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
                data = json.loads(raw)
                if data.get("type") == "welcome":
                    self._my_server_role = int(data.get("player_id", 0))

                async for message in ws:
                    try:
                        envelope = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    msg_type = envelope.get("type")

                    # ── Peer joined / left ────────────────────────────────
                    if msg_type == "peer_status":
                        if envelope.get("status") == "joined":
                            self._peer_connected = True

                    # ── Server resolved the roles ─────────────────────────
                    elif msg_type == "role_assigned":
                        self.assigned_role = int(envelope.get("assigned_role", 0))

                    # ── Peer relay (unused here but consumed cleanly) ──────
                    elif msg_type == "relay":
                        pass

        except Exception as exc:
            print(f"[WaitingRoom] WS error: {exc}")

    def _send_pref(self):
        """Send our role preference to the server."""
        if self._my_pref is None or self._ws is None:
            return
        payload = json.dumps({"type": "role_pref", "pref": self._my_pref})

        async def _send():
            try:
                await self._ws.send(payload)
            except Exception:
                pass

        self._schedule(_send())

    # ──────────────────────────────────────── UI build ───────────────────────

    def _build_ui(self):
        # Background image with parallax
        self._bg = DirectFrame(
            frameColor=(1, 1, 1, 0),
            frameSize=(-1, 1, -1, 1),
            parent=self.render2d,
        )
        self._bg.setTransparency(TransparencyAttrib.MAlpha)
        self._bg["image"] = "assets/images/menu_background.jpg"
        self._bg.setScale(1.02)

        # Semi-transparent dark overlay for readability
        DirectFrame(
            frameColor=(0.0, 0.02, 0.08, 0.70),
            frameSize=(-2, 2, -2, 2),
            parent=self.render2d,
            sortOrder=1,
        )

        # Title
        OnscreenText(
            text="CHOOSE YOUR SIDE",
            pos=(0, 0.80),
            scale=0.10,
            fg=self._blue_glow,
            shadow=(0, 0.04, 0.1, 0.9),
            align=TextNode.ACenter,
            parent=self.render2d,
            mayChange=False,
        )
        OnscreenText(
            text="Select the role you wish to play.\n"
                 "If both players choose the same side, roles will be randomised.",
            pos=(0, 0.63),
            scale=0.046,
            fg=self._dim_white,
            shadow=(0, 0, 0, 0.7),
            align=TextNode.ACenter,
            parent=self.render2d,
            mayChange=False,
        )

        # Side cards
        self._card_hero = self._make_side_card(
            role=ROLE_HERO, cx=-0.50,
            on_click=lambda: self._on_pick(ROLE_HERO),
        )
        self._card_boss = self._make_side_card(
            role=ROLE_BOSS, cx=0.50,
            on_click=lambda: self._on_pick(ROLE_BOSS),
        )

        # Selection feedback text
        self._selection_text = OnscreenText(
            text="",
            pos=(0, -0.52),
            scale=0.058,
            fg=self._soft_white,
            shadow=(0, 0, 0, 0.8),
            align=TextNode.ACenter,
            parent=self.render2d,
            mayChange=True,
        )

        # Status bar at the bottom
        self._status_frame = DirectFrame(
            frameColor=(0.0, 0.0, 0.05, 0.82),
            frameSize=(-0.80, 0.80, -0.12, 0.12),
            pos=(0, 0, -0.76),
            parent=self.render2d,
            sortOrder=5,
        )
        self._status_main = OnscreenText(
            text="Connecting to server\u2026",
            pos=(0, 0.03),
            scale=0.052,
            fg=self._soft_white,
            align=TextNode.ACenter,
            parent=self._status_frame,
            mayChange=True,
        )
        self._status_sub = OnscreenText(
            text="",
            pos=(0, -0.055),
            scale=0.038,
            fg=self._dim_white,
            align=TextNode.ACenter,
            parent=self._status_frame,
            mayChange=True,
        )

        # Launch WS in background
        self._schedule(self._ws_handler())

    def _make_side_card(self, role: int, cx: float, on_click) -> DirectFrame:
        color = ROLE_COLORS[role]
        label = ROLE_LABELS[role]
        desc  = ROLE_DESCRIPTIONS[role]

        card = DirectFrame(
            frameColor=(color[0]*0.10, color[1]*0.10, color[2]*0.10, 0.88),
            frameSize=(-0.40, 0.40, -0.40, 0.40),
            pos=(cx, 0, 0.10),
            parent=self.render2d,
            sortOrder=3,
        )

        OnscreenText(
            text=label,
            pos=(0, 0.28),
            scale=0.095,
            fg=color,
            shadow=(0, 0, 0, 0.9),
            align=TextNode.ACenter,
            parent=card,
            mayChange=False,
        )
        # Thin decorative line
        OnscreenText(
            text="\u2500" * 18,
            pos=(0, 0.20),
            scale=0.038,
            fg=(color[0], color[1], color[2], 0.40),
            align=TextNode.ACenter,
            parent=card,
            mayChange=False,
        )
        OnscreenText(
            text=desc,
            pos=(0, 0.07),
            scale=0.041,
            fg=self._soft_white,
            shadow=(0, 0, 0, 0.5),
            align=TextNode.ACenter,
            parent=card,
            mayChange=False,
        )

        btn_color_normal  = (color[0]*0.22, color[1]*0.22, color[2]*0.22, 1.0)
        btn_color_hovered = (color[0]*0.44, color[1]*0.44, color[2]*0.44, 1.0)

        btn = DirectButton(
            text=f"PLAY AS {label}",
            scale=0.056,
            pos=(0, 0, -0.30),
            parent=card,
            frameColor=btn_color_normal,
            frameSize=(-2.9, 2.9, -0.72, 0.92),
            relief="flat",
            text_fg=color,
            text_shadow=(0, 0, 0, 0.8),
            command=on_click,
        )
        btn.bind(DGG.ENTER, lambda e, b=btn, c=btn_color_hovered: b.__setitem__("frameColor", c))
        btn.bind(DGG.EXIT,  lambda e, b=btn, c=btn_color_normal:  b.__setitem__("frameColor", c))

        card._select_btn = btn
        return card

    # ──────────────────────────────────────── callbacks ──────────────────────

    def _on_pick(self, role: int):
        if self._my_pref is not None:
            return  # already locked in
        if self._my_server_role is None:
            self._set_status("Not connected yet — please wait.", "")
            return

        self._my_pref = role
        color = ROLE_COLORS[role]
        self._selection_text.setText(
            f"You chose:  {ROLE_LABELS[role]}  \u2014 waiting for opponent\u2026"
        )
        self._selection_text["fg"] = color

        self._dim_card(self._card_hero, selected=(role == ROLE_HERO))
        self._dim_card(self._card_boss, selected=(role == ROLE_BOSS))
        self._set_status(
            f"Preference sent: {ROLE_LABELS[role]}",
            "Waiting for the other player\u2026",
        )
        self._send_pref()

    def _dim_card(self, card: DirectFrame, selected: bool):
        if selected:
            card["frameColor"] = (0.04, 0.08, 0.16, 0.96)
        else:
            card["frameColor"] = (0.03, 0.03, 0.04, 0.55)
            btn = getattr(card, "_select_btn", None)
            if btn:
                btn["text_fg"]     = self._dim_white
                btn["frameColor"]  = (0.04, 0.04, 0.05, 0.55)
                btn["command"]     = lambda: None

    def _set_status(self, main: str, sub: str = ""):
        self._status_main.setText(main)
        self._status_sub.setText(sub)

    # ──────────────────────────────────────── tasks ──────────────────────────

    def _mouse_parallax(self, task):
        if self.mouseWatcherNode.hasMouse():
            x = self.mouseWatcherNode.getMouseX()
            y = self.mouseWatcherNode.getMouseY()
            self._bg.setPos(x * -0.018, 0, y * -0.018)
        return task.cont

    def _task_update(self, task):
        # ── Dynamic status text ───────────────────────────────────────────
        if self._my_server_role is None:
            self._set_status(
                "Connecting to server\u2026",
                self._ws_uri,
            )
        elif self._my_pref is None:
            if not self._peer_connected:
                self._set_status(
                    "Connected \u2014 waiting for opponent to join\u2026",
                    f"You are Player {self._my_server_role + 1}  \u2502  {self._host}:{self._port}",
                )
            else:
                self._set_status(
                    "Both players connected \u2014 choose your side!",
                    f"You are Player {self._my_server_role + 1}",
                )

        # ── Role resolved by server ───────────────────────────────────────
        if self.assigned_role is not None and not self.start_requested:
            role_name = ROLE_LABELS[self.assigned_role]
            color = ROLE_COLORS[self.assigned_role]
            self._selection_text.setText(f"\u2736  You will play as  {role_name}  \u2736")
            self._selection_text["fg"] = color
            self._set_status(
                f"Role assigned: {role_name}",
                "Starting the game\u2026",
            )
            os.environ["DUNGEON_ARISE_ROLE"] = str(self.assigned_role)
            self.start_requested = True
            self.taskMgr.doMethodLater(2.0, self._finish, "wr_finish")

        return task.cont

    def _finish(self, task=None):
        self.taskMgr.stop()
        return None
