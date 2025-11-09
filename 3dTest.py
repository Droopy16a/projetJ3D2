from direct.showbase.ShowBase import ShowBase
from panda3d.core import Vec3, DirectionalLight, AmbientLight, Vec4, WindowProperties, loadPrcFileData
from direct.actor.Actor import Actor
from panda3d.bullet import BulletWorld, BulletRigidBodyNode, BulletBoxShape, BulletDebugNode
from panda3d.core import BitMask32, TransformState, Texture, Filename, PNMImage
from direct.interval.IntervalGlobal import Sequence, ActorInterval, Func
import math
# import sys
# sys.path.append("./panda3d-simplepbr/")
import simplepbr
import imageio.v3 as iio
import numpy as np
from simplepbr.envmap import EnvMap
import panda3d.core as p3d
import complexpbr

loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #f")
# loadPrcFileData("", "framebuffer-srgb true")
class Game(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()

        # hdr_path = "./env.hdr"
        # env_cubemap = EnvMap.__new__(EnvMap)
        # env_cubemap.cubemap = p3d.Texture()

        simplepbr.init(
            use_normal_maps=True,
            enable_shadows=True,
            use_emission_maps=True,
            use_330=True,
            env_map="HDR_029_Sky_Cloudy_Env.exr"
            )
        # complexpbr.apply_shader(self.render)

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
        ground_shape = BulletBoxShape(Vec3(500, 500, 1))
        ground_node = BulletRigidBodyNode('Ground')
        ground_node.addShape(ground_shape)
        ground_node.setMass(0)
        ground_np = self.render.attachNewNode(ground_node)
        ground_np.setPos(0, 400, 0)
        ground_np.setHpr(270, 0, 0)
        self.physics_world.attachRigidBody(ground_node)

        self.level = self.loader.loadModel("models/level.glb")
        self.level.reparentTo(ground_np)
        self.level.setScale(10.0)

        # init de la physique
        char_shape = BulletBoxShape(Vec3(0.5, 0.5, 1))
        self.char_node = BulletRigidBodyNode('Character')
        self.char_node.setMass(70)
        self.char_node.addShape(char_shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.char_node.setAngularFactor(Vec3(0, 0, 0))
        self.char_np = self.render.attachNewNode(self.char_node)
        self.char_np.setPos(0, 0, 5)
        self.physics_world.attachRigidBody(self.char_node)

        cube_shape = BulletBoxShape(Vec3(1, 1, 1))
        cube_node = BulletRigidBodyNode('Cube')
        cube_node.setMass(20)
        cube_node.addShape(cube_shape, TransformState.makePos(Vec3(0, 0, 1)))
        cube_np = self.render.attachNewNode(cube_node)
        cube_np.setPos(2, 0, 0)
        self.physics_world.attachRigidBody(cube_node)
        cube_vis = self.loader.loadModel("models/box.glb")
        cube_vis.reparentTo(cube_np)
        cube_vis.setScale(1)

        # Importation du model
        self.character = Actor("models/perso6.glb")
        self.character.reparentTo(self.char_np)
        self.character.setScale(1.0)

        #l'épée
        debug_node = BulletDebugNode('BulletDebug')
        debug_np = self.render.attachNewNode(debug_node)
        debug_np.show()
        self.physics_world.setDebugNode(debug_node)

        # sword_shape = BulletBoxShape(Vec3(0.5, 1.75, 0.5))
        sword_shape = BulletBoxShape(Vec3(0.05, 1.25, 0.5))
        self.sword_node = BulletRigidBodyNode('Sword')
        self.sword_node.setMass(0)
        self.sword_node.addShape(sword_shape, TransformState.makePos(Vec3(0, -1, 0)))
        # self.sword_node.setAngularFactor(Vec3(0, 0, 0))
        # self.sword_np = self.render.attachNewNode(self.sword_node)
        self.sword_np = self.render.attachNewNode("Sword")
        joint = self.character.exposeJoint(None, 'modelRoot', 'mixamorig:RightHand')
        # self.sword_np.reparentTo(joint)
        self.sword_np.setScale(1.0)

        self.sword_np.setPos(0, 0, 10)
        self.sword_np.setHpr(0, 0, 0)

        self.physics_world.attachRigidBody(self.sword_node)
        self.sword = self.loader.loadModel("models/sword.glb")
        self.sword.reparentTo(self.sword_np)
        self.sword.setScale(1.0)
        

        # Setup de l'anim
        anims = list(self.character.getAnimNames())
        print("Animations:", anims)

        self.IDLE_ANIM = "idle"
        self.WALK_ANIM = "runvrai"
        self.JUMP_ANIM = "jumpstatvrai"

        if self.IDLE_ANIM in anims:
            self.character.loop(self.IDLE_ANIM)
        elif len(anims) > 0:
            print(f"[WARN] idle animation not found, looping {anims[0]}")
            self.character.loop(anims[0])
        else:
            print("[WARN] no animations found in model.")

        # Bon les touches quoi
        self.speed = 10.0
        self.jump_strength = 7.0
        self.keys = {"z": False, "q": False, "s": False, "d": False}
        self.is_moving = False
        self.is_jumping = False
        self.is_charging_jump = False
        self.jump_crouch_frame = 10
        self.jump_fly_frame = 25
        self.jump_sequence = None
        self.charge = 5

        self.accept("z", self.set_key, ["z", True])
        self.accept("z-up", self.set_key, ["z", False])
        self.accept("s", self.set_key, ["s", True])
        self.accept("s-up", self.set_key, ["s", False])
        self.accept("q", self.set_key, ["q", True])
        self.accept("q-up", self.set_key, ["q", False])
        self.accept("d", self.set_key, ["d", True])
        self.accept("d-up", self.set_key, ["d", False])
        self.accept("space", self.start_jump_charge)
        self.accept("space-up", self.perform_jump)

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
            if hit_node.getName() == "Ground" or hit_node.getName() == "Cube":
                return True
        return False
    
    def start_jump_charge(self):
        if self.is_on_ground() and not self.is_jumping:
            self.is_charging_jump = True
            self.character.stop()
            if self.JUMP_ANIM in self.character.getAnimNames():
                if self.jump_sequence:
                    self.jump_sequence.finish()

                jump_crouch = ActorInterval(
                    self.character,
                    self.JUMP_ANIM,
                    startFrame=0,
                    endFrame=self.jump_crouch_frame
                )

                run_crouch = ActorInterval(
                    self.character,
                    self.WALK_ANIM,
                    startFrame=0
                )

                crouch_func = Func(self.character.pose, self.JUMP_ANIM, self.jump_crouch_frame + 1)
                run_func = Func(self.character.loop, self.WALK_ANIM)

                self.crouch_sequence = Sequence(jump_crouch, crouch_func) if not self.is_moving else Sequence(run_crouch, run_func)
                
                self.crouch_sequence.start()

    def perform_jump(self):
        if self.is_charging_jump and self.is_on_ground():
            self.is_charging_jump = False
            self.is_jumping = True

            vel = self.char_node.getLinearVelocity()
            vel.setZ(self.charge)
            self.char_node.setLinearVelocity(vel)
            self.charge = 5

            if self.JUMP_ANIM in self.character.getAnimNames():
                if self.jump_sequence:
                    self.jump_sequence.finish()

                jump_anim = ActorInterval(
                    self.character,
                    self.JUMP_ANIM,
                    startFrame=self.jump_crouch_frame,
                    endFrame=self.jump_fly_frame
                )

                jump_anim_end = ActorInterval(
                    self.character,
                    self.JUMP_ANIM,
                    startFrame=self.jump_fly_frame + 1
                )

                finish_func = Func(self.character.pose, self.JUMP_ANIM, self.jump_fly_frame + 1)
                self.jump_sequence = Sequence(jump_anim, finish_func)
                self.land = Sequence(finish_func, jump_anim_end)
                self.jump_sequence.start()

    def update(self, task):
        dt = globalClock.getDt()
        move_x = float(self.keys["d"]) - float(self.keys["q"])
        move_y = float(self.keys["z"]) - float(self.keys["s"])
        move_vec = Vec3(move_x, move_y, 0)
        self.camera.setPos(self.char_np.getPos()[0], *tuple(self.camera.getPos())[1:])
        joint = self.character.exposeJoint(None, 'modelRoot', 'mixamorig:RightHand')

        self.sword_np.setHpr(self.char_np.getHpr()[0] + joint.getHpr()[0] - 90, -joint.getHpr()[1], joint.getHpr()[2] + 90)
        # self.sword_np.setPos(self.char_np, joint.getPos(self.char_np) + Vec3(0, 0, 0))
        if self.is_moving or self.is_charging_jump:
            self.sword_np.setPos(self.char_np, joint.getPos(self.char_np) + Vec3(0.0, 0.0, 0.0))
        else:
            self.sword_np.setPos(self.char_np, joint.getPos(self.char_np) + Vec3(0.0, -0.5, -0.3))
        # self.sword_np.setScale(10.0)
        # self.sword_np.setPos(joint, Vec3(50, -15, 40))

        # self.sword_np.setPos(self.char_np , joint.getPos(self.render))

        on_ground = self.is_on_ground()

        if self.is_charging_jump:
            if self.charge < 10:
                self.charge += 0.1
            else:
                self.perform_jump()

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
            if on_ground and not self.is_jumping and not self.is_charging_jump:
                if current != self.WALK_ANIM and self.WALK_ANIM in self.character.getAnimNames():
                    self.character.stop()
                    self.character.loop(self.WALK_ANIM)
        else:
            vel = self.char_node.getLinearVelocity()
            vel.setX(0)
            vel.setY(0)
            self.char_node.setLinearVelocity(vel)

            if on_ground and not self.is_jumping and not self.is_charging_jump:
                current = self.character.getCurrentAnim()
                if current != self.IDLE_ANIM and self.IDLE_ANIM in self.character.getAnimNames() and current != self.JUMP_ANIM:
                    self.character.stop()
                    self.character.loop(self.IDLE_ANIM)
                self.is_moving = False

        if on_ground and self.is_jumping:
            self.is_jumping = False
            if not self.is_charging_jump:
                self.character.play(self.JUMP_ANIM, fromFrame=self.jump_fly_frame + 1)

        elif not on_ground:
            self.is_jumping = True

        return task.cont

game = Game()
game.run()