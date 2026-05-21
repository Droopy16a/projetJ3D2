# Mode en ligne — résumé technique

## Vue d’ensemble
Le mode en ligne repose sur WebSocket avec un serveur minimaliste qui relaie les messages entre deux clients. Chaque client simule localement son rôle, envoie ses états et événements, et applique les effets reçus. Il n’y a pas d’autorité serveur ni de correction centralisée. Les entités distantes sont interpolées côté client.

Fichiers principaux
- `server.py`
- `game_client.py`
- `assets/Character.py`
- `assets/Mob.py`

## Architecture générale
1. Serveur WebSocket relayant les messages sans logique de jeu.
2. Deux rôles possibles: `ROLE_HERO = 0`, `ROLE_BOSS = 1`.
3. Chaque client est autoritaire sur son rôle et calcule localement les impacts.
4. Les positions et animations distantes sont synchronisées par envoi périodique d’état.

## Connexion, rôles, environnement
- Connexion client: `ws://{DUNGEON_ARISE_HOST}:{DUNGEON_ARISE_PORT}` avec défaut `127.0.0.1:8765`.
- Attribution de rôle par le serveur, refus d’un 3e client avec `code=4000` et raison `"Server full"`.
- Message serveur `welcome` pour fixer `player_id`.
- Graine du monde: `DUNGEON_WORLD_SEED` si défini, sinon hash de `host:port` pour cohérence entre clients.

## Protocole de messages
Messages serveur ? client
```json
{"type":"welcome","player_id":0|1}
{"type":"peer_status","role":0|1,"status":"joined"|"left"}
{"type":"relay","from":0|1,"payload":{...}}
```

Messages client relayés
```json
{"type":"state", ...}
{"type":"attack", "target":"hero"|"boss"|"mob", "mob_id"?:int, "damage":int}
{"type":"phase", "unlocked":true}
{"type":"game_over", "winner":"hero"|"boss"}
```

## Cadence d’envoi et file d’attente
- Intervalle d’envoi: `NETWORK_UPDATE_INTERVAL = 0.033` (~30 Hz).
- La file `outbox` supprime les anciens messages `state` pour éviter la latence.
- Si `outbox` dépasse 300 messages, elle est tronquée aux 150 derniers.
- Le handler réseau tourne dans un event loop asyncio déclenché par `_task_websocket`.

## Synchronisation d’état (state)
- Si `player_id == 0` (Hero)
Envoi position/rotation/état d’animation du héros, `hero_hp`, `boss_phase_unlocked`.
- Si `player_id == 1` (Boss)
Envoi position/rotation/état d’animation du boss, `boss_hp`, `boss_phase_unlocked`, liste des mobs, et éventuellement la structure du monde si l’éditeur est actif.
- Le champ `controlled` est transmis par le boss mais n’est pas consommé côté distant.

## Interpolation, prédiction, animation distante
- Les positions sont stockées avec timestamp, vitesse estimée par différence d’états.
- Lissage exponentiel: `blend = 1 - exp(-NETWORK_SMOOTHING * dt)`.
- Extrapolation légère limitée par `NETWORK_PREDICTION_LIMIT`.
- Snap si la distance dépasse `SNAP_DISTANCE`.
- Animations distantes pilotées par `moving/attacking/jumping`.

Paramètres clés
- `NETWORK_SMOOTHING = 18.0`
- `NETWORK_PREDICTION_LIMIT = 0.18`
- `SNAP_DISTANCE = 6.0`
- `NETWORK_MOVE_SPEED = 0.25`
- `NETWORK_MOVE_DIST = 0.06`

## Attaques, dégâts, autorité
- L’attaquant calcule localement portée et dégâts, puis envoie `attack`.
- Le receveur applique la perte de HP sur sa propre entité.
- Le boss ignore les dégâts reçus si la phase n’est pas déverrouillée.
- La fin de partie est décidée par le joueur touché et notifiée via `game_over`.
- Les attaques des mobs AI sont générées côté boss et envoyées au héros.

## Phase boss et progression
- La phase boss est déverrouillée quand le héros atteint `goal_x`.
- Le héros envoie `{"type":"phase","unlocked":true}`.
- Le boss met à jour son état à la réception.

## Synchronisation du monde (éditeur boss)
- Si l’éditeur est actif chez le boss, l’état inclut `world.modules`.
- Le héros applique ces positions, recalcule les limites et met à jour `goal_x`.
- Un `sig` JSON évite les resynchronisations inutiles.

## Déconnexions et reconnexion
- En cas de perte, reconnexion automatique avec délai de 1.5 s.
- Lors d’un `peer_status: left`, les entités distantes correspondantes sont supprimées.
