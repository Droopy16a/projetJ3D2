from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
import math

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    Vec3,
    DirectionalLight,
    AmbientLight,
    Vec4,
    WindowProperties,
    loadPrcFileData,
    TransformState, 
    BitMask32,
    ConfigVariableString,
    LineSegs,
)
from direct.actor.Actor import Actor
from panda3d.bullet import (
    BulletWorld,
    BulletRigidBodyNode,
    BulletBoxShape,
    BulletDebugNode,
)
from direct.interval.IntervalGlobal import Sequence, ActorInterval, Func
import simplepbr


loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #f")
ConfigVariableString("bullet-filter-algorithm").setValue("groups-mask")


@dataclass
class Config:
    window_title: str = "DZ jeu - Refactor"
    gravity: Vec3 = Vec3(0, 0, -9.81)
    player_mass: float = 70.0
    mob_mass: float = 30.0
    cube_mass: float = 20.0
    ground_half_extents: Vec3 = Vec3(500, 500, 10)
    debug_physics: bool = True

    speed: float = 10.0
    jump_base: float = 5.0
    jump_charge_max: float = 10.0
    jump_charge_rate: float = 0.1

    level_model: str = "models/plat3.glb"
    player_model: str = "models/perso6.glb"
    mob_model: str = "models/mob.glb"
    cube_model: str = "models/box.glb"
    sword_model: str = "models/sword.glb"

def bit(gid: int) -> BitMask32:
    return BitMask32.bit(gid)


class PhysicsManager:
    """Wrapper around BulletWorld and debug drawing."""

    def __init__(self, gravity: Vec3, render):
        self.world = BulletWorld()
        self.world.setGravity(gravity)
        self._render = render
        self._debug_np = None

    def attach(self, node: BulletRigidBodyNode, np):
        self.world.attachRigidBody(node)

    def detach(self, node: BulletRigidBodyNode):
        self.world.removeRigidBody(node)

    def enable_debug(self):
        debug_node = BulletDebugNode('BulletDebug')
        self._debug_np = self._render.attachNewNode(debug_node)
        self._debug_np.show()
        self.world.setDebugNode(debug_node)

    def step(self, dt: float):
        self.world.doPhysics(dt, 10, 0.008)


class Character:
    """Player character with animation + bullet body + jumping logic."""

    def __init__(self, config: Config, render, loader, physics: PhysicsManager, start_pos: Vec3 = Vec3(0, 0, 5)):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        self.actor = Actor(self.config.player_model)
        self.actor.reparentTo(render)

        shape = BulletBoxShape(Vec3(0.5, 0.5, 1))
        self.node = BulletRigidBodyNode('Character')
        self.node.setMass(config.player_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        
        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        self.actor.reparentTo(self.np)

        physics.attach(self.node, self.np)

        anims = set(self.actor.getAnimNames())
        self.IDLE_ANIM = 'idle' if 'idle' in anims else (next(iter(anims)) if anims else None)
        self.WALK_ANIM = 'runvrai' if 'runvrai' in anims else self.IDLE_ANIM
        self.JUMP_ANIM = 'jumpstatvrai' if 'jumpstatvrai' in anims else None

        if self.IDLE_ANIM:
            self.actor.loop(self.IDLE_ANIM)

        self.keys: Dict[str, bool] = {k: False for k in ('z', 'q', 's', 'd')}
        self.is_moving = False
        self.is_jumping = False
        self.is_charging_jump = False

        self.jump_crouch_frame = 10
        self.jump_fly_frame = 25
        self.jump_sequence: Optional[Sequence] = None
        self.charge = self.config.jump_base

        self.speed = config.speed

    def set_key(self, key: str, value: bool):
        self.keys[key] = value

    def start_jump_charge(self):
        if self.on_ground() and not self.is_jumping:
            self.is_charging_jump = True
            self.actor.stop()

            if self.JUMP_ANIM and self.JUMP_ANIM in self.actor.getAnimNames():
                if self.jump_sequence:
                    self.jump_sequence.finish()

                crouch = ActorInterval(self.actor, self.JUMP_ANIM, startFrame=0, endFrame=self.jump_crouch_frame)
                crouch_func = Func(self.actor.pose, self.JUMP_ANIM, self.jump_crouch_frame + 1)
                self.crouch_sequence = Sequence(crouch, crouch_func)
                self.crouch_sequence.start()

    def perform_jump(self):
        if self.is_charging_jump and self.on_ground():
            self.is_charging_jump = False
            self.is_jumping = True

            vel = self.node.getLinearVelocity()
            vel.setZ(self.charge)
            self.node.setLinearVelocity(vel)
            self.charge = self.config.jump_base

            if self.JUMP_ANIM and self.JUMP_ANIM in self.actor.getAnimNames():
                if self.jump_sequence:
                    self.jump_sequence.finish()

                jump_anim = ActorInterval(self.actor, self.JUMP_ANIM, startFrame=self.jump_crouch_frame, endFrame=self.jump_fly_frame)
                finish_func = Func(self.actor.pose, self.JUMP_ANIM, self.jump_fly_frame + 1)
                self.jump_sequence = Sequence(jump_anim, finish_func)
                self.jump_sequence.start()

    def on_ground(self) -> bool:
        from_pos = self.np.getPos() + Vec3(0, 0, 0.5)
        to_pos = self.np.getPos() - Vec3(0, 0, 1.5)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        return result.hasHit()

    def update(self, dt: float):
        if self.is_charging_jump:
            if self.charge < self.config.jump_charge_max:
                self.charge += self.config.jump_charge_rate
            else:
                self.perform_jump()

        move_x = float(self.keys['d']) - float(self.keys['q'])
        move_y = float(self.keys['z']) - float(self.keys['s'])
        move_vec = Vec3(move_x, move_y, 0)

        on_ground = self.on_ground()

        if move_vec.length() > 0:
            self.is_moving = True
            move_vec.normalize()
            velocity = move_vec * self.speed
            current_z = self.node.getLinearVelocity().z
            velocity.setZ(current_z)
            self.node.setLinearVelocity(velocity)

            angle = math.degrees(math.atan2(move_x, -move_y))
            self.np.setH(angle)

            current = self.actor.getCurrentAnim()
            if on_ground and not self.is_jumping and not self.is_charging_jump:
                if current != self.WALK_ANIM and self.WALK_ANIM in self.actor.getAnimNames():
                    self.actor.stop()
                    self.actor.loop(self.WALK_ANIM)
        else:
            vel = self.node.getLinearVelocity()
            vel.setX(0)
            vel.setY(0)
            self.node.setLinearVelocity(vel)

            if on_ground and not self.is_jumping and not self.is_charging_jump:
                current = self.actor.getCurrentAnim()
                if self.IDLE_ANIM and current != self.IDLE_ANIM and current != self.JUMP_ANIM:
                    self.actor.stop()
                    self.actor.loop(self.IDLE_ANIM)
                self.is_moving = False

        if on_ground and self.is_jumping:
            self.is_jumping = False
            if not self.is_charging_jump and self.JUMP_ANIM:
                self.actor.play(self.JUMP_ANIM, fromFrame=self.jump_fly_frame + 1)
        elif not on_ground:
            self.is_jumping = True


class Mob:
    def __init__(self, config: Config, render, loader, physics: PhysicsManager, start_pos: Vec3 = Vec3(0, 0, 7), index: int = 0):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        shape = BulletBoxShape(Vec3(0.5, 0.5, 1))
        self.node = BulletRigidBodyNode('mob')
        self.node.setMass(config.mob_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.node.setAngularFactor(Vec3(0, 0, 0))

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        physics.attach(self.node, self.np)

        self.np.setCollideMask(bit(index))

        self.actor = Actor(config.mob_model)
        self.actor.reparentTo(self.np)
        if 'run' in self.actor.getAnimNames():
            self.actor.loop('run')

        self.speed = 2.5
        self.direction = 1
        self.bounds = (-20, 20)
        self.np.setH(90)

        self.ray_vis = LineSegs()
        self.ray_vis.setThickness(2)
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())


    def update(self, dt: float):
        forward = self.np.getQuat().getForward()
        forward.normalize()


        pos = self.np.getPos()
        start = pos + Vec3(0, 0, 0.5)
        from_pos = start + forward * 0.5
        to_pos   = start + forward * -0.5

        from_hitzone = start + forward * -2.5
        to_hitzone   = start + forward * 0.5

        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        hitzone = self.physics.world.rayTestClosest(from_hitzone, to_hitzone)

        self.ray_vis.reset()
        self.ray_vis.setThickness(2)

        self.ray_vis.setColor(1, 0, 0, 1)
        self.ray_vis.moveTo(from_hitzone)
        self.ray_vis.drawTo(to_hitzone)

        self.ray_node.removeNode()
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())

        if hitzone.hasHit() and hitzone.getNode().getName() == 'Character':
            print("HIT ZONE")

        if result.hasHit() and result.getNode() != self.node and result.getNode().getName() != 'mob':
            print("Mob hit:", result.getNode().getName())
            self.direction *= -1
            self.np.setH(self.np.getH() + 180)


        if pos.x > self.bounds[1]:
            self.direction = -1
            self.np.setH(-90)
        elif pos.x < self.bounds[0]:
            self.direction = 1
            self.np.setH(90)

        self.np.setPos(pos + Vec3(self.direction * self.speed * dt, 0, 0))


class Weapon:
    def __init__(self, config: Config, loader, owner_actor: Actor, owner_np):
        self.loader = loader
        self.config = config
        self.owner_actor = owner_actor
        self.owner_np = owner_np

        self.np = owner_np.attachNewNode('weapon_node')
        self.model = self.loader.loadModel(self.config.sword_model)
        self.model.reparentTo(self.np)
        self.model.setScale(1.0)

    def update(self):
        joint = self.owner_actor.exposeJoint(None, 'modelRoot', 'mixamorig:RightHand')
        if not joint:
            return
        h, p, r = self.owner_np.getHpr()[0] + joint.getHpr()[0] - 90, -joint.getHpr()[1], joint.getHpr()[2] + 90
        self.np.setHpr(h, p, r)
        self.np.setPos(self.owner_np, joint.getPos(self.owner_np) + Vec3(0.0, -0.5, -0.3))


class World:
    def __init__(self, config: Config, render, loader, physics: PhysicsManager):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        ground_shape = BulletBoxShape(config.ground_half_extents)
        ground_node = BulletRigidBodyNode('Ground')
        ground_node.addShape(ground_shape)
        ground_node.setMass(0)
        self.ground_np = render.attachNewNode(ground_node)
        self.ground_np.setPos(0, 0, -10)
        self.ground_np.setHpr(270, 0, 0)
        physics.attach(ground_node, self.ground_np)

        self.level_model = loader.loadModel(self.config.level_model)
        self.level_model.reparentTo(self.ground_np)
        self.level_model.setScale(2.5)

        cube_shape = BulletBoxShape(Vec3(1, 1, 1))
        cube_node = BulletRigidBodyNode('Cube')
        cube_node.setMass(self.config.cube_mass)
        cube_node.addShape(cube_shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.cube_np = render.attachNewNode(cube_node)
        self.cube_np.setPos(2, 0, 0)
        physics.attach(cube_node, self.cube_np)
        cube_vis = loader.loadModel(self.config.cube_model)
        cube_vis.reparentTo(self.cube_np)
        cube_vis.setScale(1)


class Game(ShowBase):
    def __init__(self, config: Config = Config()):
        super().__init__()
        self.config = config
        self.disableMouse()

        simplepbr.init(
            use_normal_maps=True,
            enable_shadows=True,
            use_emission_maps=True,
            use_330=True,
            env_map="enviro.hdr"
        )

        props = WindowProperties()
        props.setTitle(self.config.window_title)
        self.win.requestProperties(props)

        self.camera.setPos(0, -40, 6)
        self.camera.setHpr(0, 0, 0)

        dlight = DirectionalLight('dlight')
        dlight.setColor(Vec4(0.8, 0.8, 0.8, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)
        self.render.setLight(dlnp)

        alight = AmbientLight('alight')
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        self.physics = PhysicsManager(self.config.gravity, self.render)
        if self.config.debug_physics:
            self.physics.enable_debug()

        self.world = World(self.config, self.render, self.loader, self.physics)

        self.player = Character(self.config, self.render, self.loader, self.physics)

        self.weapon = Weapon(self.config, self.loader, self.player.actor, self.player.np)

        self.mob = [Mob(self.config, self.render, self.loader, self.physics), Mob(self.config, self.render, self.loader, self.physics, Vec3(10, 0, 7), 1)]

        self.accept('z', self.player.set_key, ['z', True])
        self.accept('z-up', self.player.set_key, ['z', False])
        self.accept('s', self.player.set_key, ['s', True])
        self.accept('s-up', self.player.set_key, ['s', False])
        self.accept('q', self.player.set_key, ['q', True])
        self.accept('q-up', self.player.set_key, ['q', False])
        self.accept('d', self.player.set_key, ['d', True])
        self.accept('d-up', self.player.set_key, ['d', False])
        self.accept('space', self.player.start_jump_charge)
        self.accept('space-up', self.player.perform_jump)

        self.taskMgr.add(self._task_physics, 'physics_task')
        self.taskMgr.add(self._task_update, 'update_task')

    def _task_physics(self, task):
        dt = globalClock.getDt()
        self.physics.step(dt)
        return task.cont

    def _task_update(self, task):
        dt = globalClock.getDt()

        self.player.update(dt)
        for m in self.mob:
            m.update(dt)
        self.weapon.update()

        camx, camy, camz = self.camera.getPos()
        player_x = self.player.np.getPos()[0]
        self.camera.setPos(player_x, camy, camz)

        return task.cont


if __name__ == '__main__':
    game = Game()
    game.run()
