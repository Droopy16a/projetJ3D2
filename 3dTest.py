# main.py
from direct.showbase.ShowBase import ShowBase
from panda3d.core import Vec3, DirectionalLight, AmbientLight, Vec4, WindowProperties, loadPrcFileData
from direct.actor.Actor import Actor
from panda3d.bullet import BulletWorld, BulletRigidBodyNode, BulletBoxShape
import simplepbr
import math

loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #f")

class Game(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        simplepbr.init(use_normal_maps=True, use_emission_maps=True, enable_shadows=True)

        props = WindowProperties()
        props.setTitle("DZ jeu")
        self.win.requestProperties(props)

        # Caméra
        self.camera.setPos(0, -30, 6)
        self.camera.setHpr(0, 0, 0) #hpr = rotation

        # Lumière
        dlight = DirectionalLight('dlight')
        dlight.setColor(Vec4(0.8, 0.8, 0.8, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)
        self.render.setLight(dlnp)

        alight = AmbientLight('alight')
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        # init de la physique
        self.physics_world = BulletWorld()
        self.physics_world.setGravity(Vec3(0, 0, -9.81))

        # le sol
        ground_shape = BulletBoxShape(Vec3(50, 50, 1))
        ground_node = BulletRigidBodyNode('Ground')
        ground_node.addShape(ground_shape)
        ground_node.setMass(0)
        ground_np = self.render.attachNewNode(ground_node)
        ground_np.setPos(0, 0, -2)
        self.physics_world.attachRigidBody(ground_node)

        # init de la physique
        char_shape = BulletBoxShape(Vec3(0.5, 0.5, 1))
        self.char_node = BulletRigidBodyNode('Character')
        self.char_node.setMass(70)
        self.char_node.addShape(char_shape)
        self.char_node.setAngularFactor(Vec3(0, 0, 0))
        self.char_np = self.render.attachNewNode(self.char_node)
        self.char_np.setPos(0, 0, 5)
        self.physics_world.attachRigidBody(self.char_node)

        cube_shape = BulletBoxShape(Vec3(1, 1, 1))
        cube_node = BulletRigidBodyNode('Cube')
        cube_node.setMass(10)
        cube_node.addShape(cube_shape)
        cube_np = self.render.attachNewNode(cube_node)
        cube_np.setPos(2, 0, 0)
        self.physics_world.attachRigidBody(cube_node)
        cube_vis = self.loader.loadModel("models/box.glb")
        cube_vis.reparentTo(cube_np)
        cube_vis.setScale(1)

        # Importation du model
        self.character = Actor("models/perso3.glb")
        self.character.reparentTo(self.char_np)
        self.character.setScale(1.0)

        # Setup de l'anim
        anims = list(self.character.getAnimNames())
        print("Animations:", anims)

        self.IDLE_ANIM = "idle"
        self.WALK_ANIM = "runvrai"
        self.JUMP_ANIM = "jump" if "jump" in anims else None

        if self.IDLE_ANIM in anims:
            self.character.loop(self.IDLE_ANIM)
        elif len(anims) > 0:
            print(f"[WARN] idle animation not found, looping {anims[0]}")
            self.character.loop(anims[0])
        else:
            print("[WARN] no animations found in model.")

        # Bon les touches quoi
        self.speed = 10.0
        self.jump_strength = 10.0
        self.keys = {"z": False, "q": False, "s": False, "d": False}
        self.is_moving = False
        self.is_jumping = False

        self.accept("z", self.set_key, ["z", True])
        self.accept("z-up", self.set_key, ["z", False])
        self.accept("s", self.set_key, ["s", True])
        self.accept("s-up", self.set_key, ["s", False])
        self.accept("q", self.set_key, ["q", True])
        self.accept("q-up", self.set_key, ["q", False])
        self.accept("d", self.set_key, ["d", True])
        self.accept("d-up", self.set_key, ["d", False])
        self.accept("space", self.jump)

        # Les tache à faire (liée aux fonctions)
        self.taskMgr.add(self.update_physics, "update_physics")
        self.taskMgr.add(self.update, "updateTask")

    # Geestion de la physique
    def update_physics(self, task):
        dt = globalClock.getDt()
        self.physics_world.doPhysics(dt, 10, 0.008)
        return task.cont

    # nom de touche -> touche
    def set_key(self, key, value):
        self.keys[key] = value

    # Détecte le sol
    def is_on_ground(self):
        from_pos = self.char_np.getPos() + Vec3(0, 0, 0.5)
        to_pos = self.char_np.getPos() - Vec3(0, 0, 1.5)
        result = self.physics_world.rayTestClosest(from_pos, to_pos)
        if result.hasHit():
            hit_node = result.getNode()
            if hit_node.getName() == "Ground":
                return True
        return False
    
    def jump(self):
        if self.is_on_ground():
            vel = self.char_node.getLinearVelocity()
            vel.setZ(self.jump_strength)
            self.char_node.setLinearVelocity(vel)
            self.is_jumping = True

            if self.JUMP_ANIM:
                self.character.play(self.JUMP_ANIM)

    # Pour faire bouger le perso
    def update(self, task):
        dt = globalClock.getDt()
        move_x = float(self.keys["d"]) - float(self.keys["q"])
        move_y = float(self.keys["z"]) - float(self.keys["s"])
        move_vec = Vec3(move_x, move_y, 0)
        self.camera.setPos(self.char_np.getPos()[0], *tuple(self.camera.getPos())[1:])

        on_ground = self.is_on_ground()

        if move_vec.length() > 0:
            self.is_moving = True
            move_vec.normalize()

            velocity = move_vec * self.speed
            current_z = self.char_node.getLinearVelocity().z
            velocity.setZ(current_z)
            self.char_node.setLinearVelocity(velocity)

            angle = math.degrees(math.atan2(move_x, -move_y))
            self.char_np.setH(angle)

            current = self.character.getCurrentAnim()
            if on_ground and not self.is_jumping:
                if current != self.WALK_ANIM and self.WALK_ANIM in self.character.getAnimNames():
                    self.character.stop()
                    self.character.loop(self.WALK_ANIM)
        else:
            vel = self.char_node.getLinearVelocity()
            vel.setX(0)
            vel.setY(0)
            self.char_node.setLinearVelocity(vel)

            if on_ground and not self.is_jumping:
                current = self.character.getCurrentAnim()
                if current != self.IDLE_ANIM and self.IDLE_ANIM in self.character.getAnimNames():
                    self.character.stop()
                    self.character.loop(self.IDLE_ANIM)
                self.is_moving = False

        if on_ground and self.is_jumping:
            self.is_jumping = False
            if self.IDLE_ANIM in self.character.getAnimNames():
                self.character.loop(self.IDLE_ANIM)

        return task.cont

game = Game()
game.run()
