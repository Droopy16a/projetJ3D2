from ursina import *
from direct.actor.Actor import Actor
import math

app = Ursina()

player_entity = Entity()

character = Actor('models/perso.glb')
character.reparent_to(player_entity)
character.enableBlend()

anims = character.getAnimNames()
print("Animations found:", anims)

WALK_ANIM = "Armature.004|mixamo.com|Layer0.003"
IDLE_ANIM = "Armature.003Action"

if IDLE_ANIM in anims:
    character.loop(IDLE_ANIM)

EditorCamera(rotation=(10, 0, 0), position=(0, 5, 0))

DirectionalLight(shadows=True, position=(2, 4, 5), rotation=(45, -45, 0))

Entity(model='plane', scale=20, color=color.lime, collider='box')

player_entity.collider = 'box'
player_entity.scale = 1.2
player_entity.y = 1

speed = 4


def update():
    """Called every frame"""
    is_moving = False

    move_vec = Vec2(
        held_keys['d'] - held_keys['a'],
        0
    ).normalized()

    if move_vec.length() > 0:
        is_moving = True
        player_entity.position += move_vec * time.dt * speed

        angle = math.degrees(math.atan2(move_vec.x, move_vec.y))
        player_entity.rotation_y = (angle + 180) % 360

    if anims:
        if is_moving:
            if character.getCurrentAnim() != WALK_ANIM:
                character.stop()
                character.setControlEffect(WALK_ANIM, 1.0)   # no easing/blend
                character.setPlayRate(1.0, WALK_ANIM)        # constant speed
                character.loop(WALK_ANIM, fromFrame=0, toFrame=20)
        else:
            if character.getCurrentAnim() != IDLE_ANIM:
                character.stop()
                character.setControlEffect(IDLE_ANIM, 1.0)
                character.setPlayRate(1.0, IDLE_ANIM)
                character.loop(IDLE_ANIM)


app.run()
