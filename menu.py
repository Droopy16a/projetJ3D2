from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectButton, DirectFrame, OnscreenText
from panda3d.core import TransparencyAttrib, TextNode
from panda3d.core import loadPrcFileData
from direct.gui import DirectGuiGlobals as DGG
import os
import asyncio
import socket
import threading

loadPrcFileData("", "win-size 1920 1080")

DISCOVERY_PORT = 5000


def discover_server(timeout=5):
    """Listen for server broadcast and return the IP:PORT."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(timeout)
        
        print("Searching for server on local network...")
        
        data, addr = sock.recvfrom(1024)
        message = data.decode().strip()
        
        if message.startswith("DUNGEON_SERVER:"):
            parts = message.split(":")
            if len(parts) >= 3:
                server_ip = parts[1]
                server_port = parts[2]
                if len(parts) >= 4:
                    try:
                        os.environ["DUNGEON_WORLD_SEED"] = str(int(parts[3]))
                    except ValueError:
                        pass
                sock.close()
                return f"{server_ip}:{server_port}"
        
        sock.close()
    except socket.timeout:
        pass
    except Exception as e:
        print(f"Discovery error: {e}")
    
    return None

class Menu(ShowBase):
    def __init__(self):
        super().__init__()

        self.disableMouse()
        self.start_requested = False
        self.server_host = os.getenv("DUNGEON_ARISE_HOST", "127.0.0.1")
        self.discovering_server = False
        self.discovery_thread = None

        self.blue_glow = (0.45, 0.85, 1.0, 0.9)
        self.soft_white = (1, 1, 1, 0.9)

        self.bg = DirectFrame(
            frameColor=(1, 1, 1, 0),
            frameSize=(-1, 1, -1, 1),
            parent=self.render2d
        )
        self.perso = DirectFrame(
            frameColor=(1, 1, 1, 0),
            frameSize=(-1, 1, -1, 1),
            parent=self.render2d
        )
        self.bg.setTransparency(TransparencyAttrib.MAlpha)
        self.perso.setTransparency(TransparencyAttrib.MAlpha)

        self.bg["image"] = "assets/images/menu_background.jpg"
        self.perso["image"] = "assets/images/perso.png"

        self.bg.setScale(1.02)
        self.perso.setScale(1.02)

        self.taskMgr.add(self.mouse_parallax, "bg-parallax")

        # self.title = OnscreenText(
        #     text="Dungeons Arise",
        #     pos=(0.5, 0.55),
        #     scale=0.14,
        #     fg=self.soft_white,
        #     shadow=(0, 0, 0, 0.9),
        #     align=TextNode.ACenter,
        #     mayChange=False
        # )

        self.title = DirectFrame(
            frameColor=(1, 1, 1, 0),
            frameSize=(-1, 1, -1, 1),
            parent=self.render2d
        )

        self.title.setTransparency(TransparencyAttrib.MAlpha)
        # self.title["image"] = "logo.png"

        self.buttons = []
        self.current_index = 0
        self.network_frame = None
        self.status_text = None

        self.make_button("CONTINUE", 0.5, 0.15, self.start_game)
        self.make_button("FIND SERVER", 0.5, -0.03, self.find_server)
        self.make_button("QUIT", 0.5, -0.21, self.exit_game)

        self.update_highlight()

        self.accept("arrow_up", self.navigate, [-1])
        self.accept("arrow_down", self.navigate, [1])
        self.accept("enter", self.activate)
        self.accept("escape", self.hide_network_screen)

    def make_button(self, text, x, y, command):
        btn = DirectButton(
            text=text,
            scale=0.075,
            pos=(x, 0, y),
            frameColor=(0, 0, 0, 0),
            relief="flat",
            text_fg=self.soft_white,
            text_shadow=(0, 0, 0, 0.8),
            command=command
        )

        btn.is_hovered = False
        btn.is_selected = False

        btn.bind(DGG.ENTER, lambda e, b=btn: self.on_hover(b, True))
        btn.bind(DGG.EXIT,  lambda e, b=btn: self.on_hover(b, False))

        self.buttons.append(btn)

    def on_hover(self, btn, hovered):
        btn.is_hovered = hovered
        self.refresh_button_visual(btn)

    def refresh_button_visual(self, btn):
        if btn.is_selected:
            btn["text_fg"] = self.blue_glow
            btn["text_shadow"] = (0, 0.1, 0.15, 1)
        elif btn.is_hovered:
            btn["text_fg"] = self.blue_glow
            btn["text_shadow"] = (0, 0, 0, 0.8)
        else:
            btn["text_fg"] = self.soft_white
            btn["text_shadow"] = (0, 0, 0, 0.8)

    def navigate(self, direction):
        self.current_index = (self.current_index + direction) % len(self.buttons)
        self.update_highlight()

    def update_highlight(self):
        for i, btn in enumerate(self.buttons):
            btn.is_selected = (i == self.current_index)
            self.refresh_button_visual(btn)

    def activate(self):
        self.buttons[self.current_index]["command"]()

    def mouse_parallax(self, task):
        if self.mouseWatcherNode.hasMouse():
            x = self.mouseWatcherNode.getMouseX()
            y = self.mouseWatcherNode.getMouseY()

            self.perso.setPos(x * 0.02, 0, y * 0.02)
            self.bg.setPos(x * -0.02, 0, y * -0.02)

        return task.cont

    def start_game(self):
        self.start_requested = True
        self.taskMgr.stop()

    def find_server(self):
        if self.discovering_server:
            return

        self.discovering_server = True

        # Create discovery dialog
        self.network_frame = DirectFrame(
            frameColor=(0, 0, 0, 0.7),
            frameSize=(-0.6, 0.6, -0.3, 0.3),
            pos=(0, 0, 0),
            parent=self.render2d,
            sortOrder=100
        )

        # Title
        title = OnscreenText(
            text="SEARCHING FOR SERVER",
            parent=self.network_frame,
            pos=(0, 0.2),
            scale=0.08,
            fg=self.blue_glow,
            align=TextNode.ACenter
        )

        # Status text
        self.status_text = OnscreenText(
            text="Searching on local network...",
            parent=self.network_frame,
            pos=(0, 0),
            scale=0.06,
            fg=self.soft_white,
            align=TextNode.ACenter
        )

        # Cancel button
        cancel_btn = DirectButton(
            text="CANCEL",
            scale=0.06,
            pos=(0, 0, -0.2),
            parent=self.network_frame,
            frameColor=(0, 0, 0, 0),
            relief="flat",
            text_fg=self.soft_white,
            command=self.hide_network_screen
        )

        # Start discovery in background thread
        def discover():
            result = discover_server(timeout=8)
            self.taskMgr.doMethodLater(0.1, lambda task: self.on_discovery_complete(result), "discovery_result")

        self.discovery_thread = threading.Thread(target=discover, daemon=True)
        self.discovery_thread.start()

    def on_discovery_complete(self, result):
        if result:
            self.server_host = result
            os.environ["DUNGEON_ARISE_HOST"] = result.split(":")[0]
            if self.status_text:
                self.status_text.setText(f"Server found!\n{result}\n\nStarting game...")
            self.taskMgr.doMethodLater(1.5, lambda task: self.start_game_after_discovery(), "start_game")
        else:
            if self.status_text:
                self.status_text.setText("Server not found!\n\nMake sure server is running\non the same WiFi network.\n\nPress CANCEL to try again.")

    def start_game_after_discovery(self):
        self.hide_network_screen()
        self.start_game()

    def show_network_options(self):
        pass

    def apply_network_settings(self):
        pass

    def hide_network_screen(self):
        if self.network_frame:
            self.network_frame.destroy()
            self.network_frame = None
            self.status_text = None
        self.discovering_server = False

    def exit_game(self):
        print("Exiting...")
        self.taskMgr.stop()


if __name__ == "__main__":
    menu = Menu()
    menu.run()
    start_requested = menu.start_requested
    menu.destroy()
    if start_requested:
        from game_client import Game

        game = Game()
        game.run()
