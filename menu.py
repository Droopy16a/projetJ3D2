from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectButton, DirectFrame, OnscreenText
from panda3d.core import TransparencyAttrib, TextNode
from panda3d.core import loadPrcFileData
from direct.gui import DirectGuiGlobals as DGG
loadPrcFileData("", "win-size 1920 1080")

class Menu(ShowBase):
    def __init__(self):
        super().__init__()

        self.disableMouse()
        self.start_requested = False

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

        self.make_button("CONTINUE", 0.5, 0.15, self.start_game)
        # self.make_button("NEW GAME", 0.5, -0.03, self.start_game)
        self.make_button("OPTIONS", 0.5, -0.03, self.show_options)
        # self.make_button("OPTIONS", 0.5, -0.21, self.show_options)
        self.make_button("QUIT", 0.5, -0.21, self.exit_game)
        # self.make_button("QUIT", 0.5, -0.39, self.exit_game)

        self.update_highlight()

        self.accept("arrow_up", self.navigate, [-1])
        self.accept("arrow_down", self.navigate, [1])
        self.accept("enter", self.activate)

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

    def show_options(self):
        print("Opening options...")

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
