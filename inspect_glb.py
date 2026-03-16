from __future__ import annotations

import sys
from pathlib import Path

from panda3d.core import LMatrix4, loadPrcFileData


def _configure_headless():
    loadPrcFileData("", "window-type none")
    loadPrcFileData("", "audio-library-name null")


def _find_singular_mats(root, label: str, limit: int = 20):
    singular = []
    for np in root.find_all_matches("**"):
        if np.isEmpty():
            continue
        try:
            mat = LMatrix4(np.getMat())
            ok = mat.invertInPlace()
        except Exception as exc:  # pragma: no cover - defensive for odd node types
            ok = False
            singular.append(f"{label}:{np.getName()} (exc: {exc})")
            if len(singular) >= limit:
                break
        if not ok:
            singular.append(f"{label}:{np.getName()}")
            if len(singular) >= limit:
                break
    return singular


def _find_suspicious_scales(root, label: str, limit: int = 20):
    zero_like = []
    non_unit = []
    eps = 1e-6
    for np in root.find_all_matches("**"):
        if np.isEmpty():
            continue
        sx, sy, sz = np.getScale()
        if abs(sx) < eps or abs(sy) < eps or abs(sz) < eps:
            zero_like.append(f"{label}:{np.getName()} scale=({sx:.6g}, {sy:.6g}, {sz:.6g})")
            if len(zero_like) >= limit:
                break
        if abs(sx - 1.0) > 1e-3 or abs(sy - 1.0) > 1e-3 or abs(sz - 1.0) > 1e-3:
            non_unit.append(f"{label}:{np.getName()} scale=({sx:.6g}, {sy:.6g}, {sz:.6g})")
            if len(non_unit) >= limit:
                break
    return zero_like, non_unit


def main():
    if len(sys.argv) < 2:
        print("Usage: py -3.14 .\\inspect_glb.py path\\to\\model.glb")
        return 2

    model_path = Path(sys.argv[1])
    if not model_path.exists():
        print(f"[error] File not found: {model_path}")
        return 2

    _configure_headless()
    from direct.showbase.ShowBase import ShowBase
    from direct.actor.Actor import Actor

    base = ShowBase()
    try:
        print(f"[info] Loading model: {model_path}")
        model = base.loader.loadModel(str(model_path))
        print(f"[info] Model empty: {model.isEmpty()}")

        char_nodes = model.find_all_matches("**/+Character")
        joint_nodes = model.find_all_matches("**/+CharacterJoint")
        print(f"[info] Model Character nodes: {char_nodes.get_num_paths()}")
        print(f"[info] Model CharacterJoint nodes: {joint_nodes.get_num_paths()}")

        zero_scales, non_unit = _find_suspicious_scales(model, "model")
        if zero_scales:
            print("[warn] Zero-like scales in model:")
            for line in zero_scales:
                print(f"  - {line}")
        else:
            print("[info] No zero-like scales found in model.")

        if non_unit:
            print("[info] Non-unit scales in model (sample):")
            for line in non_unit:
                print(f"  - {line}")

        singular = _find_singular_mats(model, "model")
        if singular:
            print("[warn] Singular transforms in model (sample):")
            for line in singular:
                print(f"  - {line}")
        else:
            print("[info] No singular transforms found in model.")

        print("[info] Trying Actor(...)")
        actor = None
        try:
            actor = Actor(str(model_path))
            print("[info] Actor created successfully.")
        except Exception as exc:
            print(f"[error] Actor failed: {exc}")

        if actor:
            actor_chars = actor.find_all_matches("**/+Character")
            actor_joints = actor.find_all_matches("**/+CharacterJoint")
            print(f"[info] Actor Character nodes: {actor_chars.get_num_paths()}")
            print(f"[info] Actor CharacterJoint nodes: {actor_joints.get_num_paths()}")

            zero_scales, non_unit = _find_suspicious_scales(actor, "actor")
            if zero_scales:
                print("[warn] Zero-like scales in actor:")
                for line in zero_scales:
                    print(f"  - {line}")
            else:
                print("[info] No zero-like scales found in actor.")

            if non_unit:
                print("[info] Non-unit scales in actor (sample):")
                for line in non_unit:
                    print(f"  - {line}")

            singular = _find_singular_mats(actor, "actor")
            if singular:
                print("[warn] Singular transforms in actor (sample):")
                for line in singular:
                    print(f"  - {line}")
            else:
                print("[info] No singular transforms found in actor.")
    finally:
        base.destroy()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
