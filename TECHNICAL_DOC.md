# Projet J3D2 - Deep Technical Specification

## 1. Networking & State Synchronization
The game uses a **Hybrid Relay Architecture** built on WebSockets for reliable messaging and UDP for local discovery.

### 1.1 Local Discovery Protocol
- **Service**: `server.py`
- **Broadcast**: Every 1 second on UDP port 5000.
- **Payload**: `DUNGEON_SERVER:<IP>:<PORT>:<SEED>`
- **Client Side**: `menu.py` listens for these broadcasts to auto-populate the connection URI.

### 1.2 WebSocket Protocol
- **URI Schema**: `ws://<host>:<port>`
- **Role Assignment**: Server assigns `ROLE_HERO (0)` or `ROLE_BOSS (1)` on connection. If full, returns code `4000`.
- **Message Relay**: Server relays all messages to the peer, prepending a `from` field indicating the sender's role.

### 1.3 Synchronization Strategy
- **Tick Rate**: Updates sent at 33ms intervals (~30Hz).
- **Freshest-State Strategy**: The `_pending_state_payload` buffer in `game_client.py` ensures only the most recent state update is sent, preventing network congestion from stale snapshots.
- **Smoothing & Prediction**:
    - **Smoothing**: Exponential moving average (`1 - exp(-SMOOTHING * dt)`).
    - **Extrapolation**: Limited to 180ms (`NETWORK_PREDICTION_LIMIT`) to prevent "ghosting" on packet loss.
    - **Snapping**: Entities snap to target positions if the distance exceeds `SNAP_DISTANCE` (6.0 units).

---

## 2. World System: Modular Geometry
### 2.1 Seed-Based Generation
- **Algorithm**: Pseudo-random sequence generated using `random.Random(seed)`.
- **Structure**: Always starts and ends with a `base` module (locked endpoints). The middle is a randomized sequence of modules from `assets/models/modules`.
- **Metadata**: Each module carries `width`, `center_offset`, and `min/max_bound` used for precise placement and AI navigation.

### 2.2 Dynamic Dungeon Manipulation (War Table)
- **Mapping**: A 2D-to-3D projection maps the 2D War Table UI positions to the 3D world.
- **Real-time Linking**: When a Boss moves a module, the `World.py` logic re-calculates the `current_x` chain.
- **Entity Teleportation**: Entities standing on a module are assigned a `module_id`. When the module moves, the entity's position is updated by the module's `delta_x/z` to prevent them from falling into the void.

---

## 3. Entity & Combat Mechanics
### 3.1 Advanced Movement Logic
- **Coyote Time**: 110ms window allowing jumps after leaving a platform.
- **Jump Buffering**: 140ms window to queue a jump before hitting the ground.
- **Ledge Climbing**:
    - Uses 3-point raycasting:
        1. **Chest Ray**: Detects wall presence.
        2. **Head Ray**: Ensures no obstruction above the ledge.
        3. **Ledge Ray**: Downward cast to find the exact landing Z-coordinate.

### 3.2 AI Steering & Sensing
- **Obstacle Avoidance**: Forward-facing raycasts detect geometry or other entities.
- **Ground Detection**: Downward diagonal raycasts detect upcoming ledges to prevent AIs from walking off platforms unintentionally.
- **Targeting**: Sphere/Box overlap checks for combat detection.

### 3.3 Combat Math
- **Combo System**:
    - Multipliers: `(1.0, 1.18, 1.35)` applied sequentially if attacks occur within `COMBO_WINDOW` (850ms).
    - Range Bonus: `(0.0, 0.18, 0.34)` units added to attack hitbox.
- **Hit-Stop**: Game time is effectively "paused" for 45ms (`HITSTOP_DURATION`) upon a successful hit to increase impact feel.
- **Lunge**: Attack animations apply a forward impulse using `node.setLinearVelocity`.

---

## 4. Physics Configuration (Bullet)
- **Filtering**: Uses `BitMask32` for collision groups. Mobs are assigned incremental bits to avoid self-collision while allowing interaction with the Hero.
- **Gravity**: Standard `-9.81 m/s²` applied globally via `PhysicsManager.py`.
- **Hitbox Pipeline**:
    - Geometry is extracted from `.glb` using `find_all_matches("**/+GeomNode")`.
    - `BulletTriangleMeshShape` is used for static environment modules to allow high-precision collision.
    - `BulletCapsuleShape` is used for dynamic entities to prevent snagging on geometry edges.

---

## 5. Rendering & VFX
- **PBR Pipeline**: `simplepbr` initialized with:
    - Shadow mapping (2048x2048).
    - Environment mapping (`cubemap.env`).
    - MSAA (8 samples).
- **VFX System**: Procedural pulse effects (scaled spheres with alpha fade) and billboarded damage text.

---

## 6. Network Message Schemas
### 6.1 State Payload (Hero)
```json
{
  "type": "state",
  "hero": {
    "x": 12.5, "z": 4.2, "h": 90.0,
    "moving": true, "jumping": false,
    "attacking": false, "attack_id": 42
  },
  "hero_hp": 100,
  "hero_level": 5
}
```

### 6.2 Attack Payload
```json
{
  "type": "attack",
  "source": "hero",
  "damage": 15,
  "pos": [13.0, 0, 4.2],
  "is_big": false
}
```
