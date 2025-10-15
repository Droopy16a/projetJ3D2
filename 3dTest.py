# main.py
from direct.showbase.ShowBase import ShowBase
from panda3d.core import Vec3, DirectionalLight, AmbientLight, Vec4, KeyboardButton, WindowProperties
from direct.actor.Actor import Actor
import math
from panda3d.core import Shader, Texture, TransparencyAttrib
from panda3d.core import loadPrcFileData
from panda3d.core import TextureStage

loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #t")

class Game(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        self.disableMouse()

        props = WindowProperties()
        props.setTitle("Panda3D Character Controller Example")
        self.win.requestProperties(props)

        self.camera.setPos(0, -10, 4)
        self.camera.setHpr(0, -10, 0)

        dlight = DirectionalLight('dlight')
        dlight.setColor(Vec4(0.8, 0.8, 0.8, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)
        self.render.setLight(dlnp)

        alight = AmbientLight('alight')
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        self.character = Actor("models/perso2.glb")
        self.character.clearMaterial()

        Marmor25 = self.character.findMaterial("Material__25.006")

        armor25 = self.character.find("**/armor.008")

        armor25.setMaterial(Marmor25, 1)

        anims = list(self.character.getAnimNames())
        print("Animations found in perso.glb:", anims)

        self.character.reparentTo(self.render)
        self.character.setScale(1.0)
        self.character.setPos(0, 0, 0)

        self.IDLE_ANIM = "idle"
        self.WALK_ANIM = "runvrai"

        if self.IDLE_ANIM in anims:
            self.character.loop(self.IDLE_ANIM)
        elif len(anims) > 0:
            print(f"[WARN] idle animation not found, looping {anims[0]}")
            self.character.loop(anims[0])
        else:
            print("[WARN] no animations found in model.")

        self.speed = 5.0
        self.keys = {"z": False, "q": False, "s": False, "d": False}
        self.is_moving = False

        self.accept("z", self.set_key, ["z", True])
        self.accept("z-up", self.set_key, ["z", False])
        self.accept("s", self.set_key, ["s", True])
        self.accept("s-up", self.set_key, ["s", False])
        self.accept("q", self.set_key, ["q", True])
        self.accept("q-up", self.set_key, ["q", False])
        self.accept("d", self.set_key, ["d", True])
        self.accept("d-up", self.set_key, ["d", False])

        self.taskMgr.add(self.update, "updateTask")

    def set_key(self, key, value):
        self.keys[key] = value

    def update(self, task):
        dt = globalClock.getDt()
        move_x = float(self.keys["d"]) - float(self.keys["q"])
        move_y = float(self.keys["z"]) - float(self.keys["s"])

        move_vec = Vec3(move_x, move_y, 0)

        if move_vec.length() > 0:
            self.is_moving = True
            move_vec.normalize()

            self.character.setPos(self.character.getPos() + move_vec * dt * self.speed)

            angle = math.degrees(math.atan2(move_x, -move_y))
            self.character.setH(angle)

            current = self.character.getCurrentAnim()
            if current != self.WALK_ANIM and self.WALK_ANIM in self.character.getAnimNames():
                self.character.stop()
                self.character.loop(self.WALK_ANIM)
        else:
            if self.is_moving:
                current = self.character.getCurrentAnim()
                if current != self.IDLE_ANIM and self.IDLE_ANIM in self.character.getAnimNames():
                    self.character.stop()
                    self.character.loop(self.IDLE_ANIM)
                self.is_moving = False

        return task.cont

game = Game()
game.run()