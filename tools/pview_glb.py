from __future__ import annotations

import sys
from pathlib import Path

from panda3d.core import loadPrcFileData


def _configure():
    loadPrcFileData("", "window-title GLB Preview")


def main():
    if len(sys.argv) < 2:
        print("Usage: py -3.14 .\\pview_glb.py path\\to\\model.glb")
        return 2

    model_path = Path(sys.argv[1])
    if not model_path.exists():
        print(f"[error] File not found: {model_path}")
        return 2

    _configure()
    from direct.showbase.ShowBase import ShowBase
    from direct.actor.Actor import Actor

    base = ShowBase()
    try:
        print(f"[info] Loading model: {model_path}")
        model = base.loader.loadModel(str(model_path))
        if model.isEmpty():
            print("[error] Loaded empty model.")
            return 1

        has_character = model.find_all_matches("**/+Character").get_num_paths() > 0
        if has_character:
            print("[info] Character rig detected; previewing via Actor.")
            try:
                actor = Actor(str(model_path))
                actor.reparentTo(base.render)
                actor.setPos(0, 6, 0)
                anims = actor.getAnimNames()
                if anims:
                    actor.loop(anims[0])
            except Exception as exc:
                print(f"[warn] Actor failed, falling back to static model: {exc}")
                model.reparentTo(base.render)
        else:
            print("[info] No Character rig detected; previewing static model.")
            model.reparentTo(base.render)

        base.render.setTwoSided(True)
        base.trackball.node().set_pos(0, 30, 0)
        base.trackball.node().set_hpr(0, 0, 0)
        base.run()
    finally:
        base.destroy()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
