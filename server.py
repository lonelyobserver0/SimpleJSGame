#!/usr/bin/env python3
import asyncio, websockets, json, time, math, uuid, random

# CONFIG
TICK_RATE = 20
BROADCAST_RATE = 20
MOVE_SPEED = 5.0
RUN_MULTIPLIER = 1.8
CROUCH_MULTIPLIER = 0.5
MAX_HEALTH = 100
RESPAWN_TIME = 5.0

WEAPON_DATA = {
    "pistol": {"damage": 20, "range": 25, "mag": 12, "fire_rate": 0.4},
    "rifle": {"damage": 34, "range": 35, "mag": 30, "fire_rate": 0.1},
    "shotgun": {"damage": 10, "range": 15, "pellets": 5, "mag": 8, "fire_rate": 1.0}
}

WEAPON_SPAWN_INTERVAL = 5.0
WEAPON_MAX = 10

# GLOBAL STATE
clients = {}       # ws -> pid
players = {}       # pid -> player dict
weapons = {}       # wid -> weapon dict
projectiles = []   # list of {pos, dir, owner, type, time}

# UTILS
def now(): 
    return time.time()

def vec_len(v): 
    return math.sqrt(sum([x*x for x in v]))

def normalize(v): 
    L = vec_len(v)
    return (0, 0, 0) if L == 0 else tuple(x/L for x in v)

def rotate_yaw_forward(yaw, amt=1.0): 
    return (math.sin(yaw)*amt, math.cos(yaw)*amt)

# NOTIFY
async def notify_player_byid(pid, msg):
    for ws, _pid in clients.items():
        if _pid == pid:
            try: 
                await ws.send(json.dumps(msg))
            except: 
                pass

async def notify_all(msg):
    data = json.dumps(msg)
    await asyncio.gather(*[ws.send(data) for ws in clients.keys()], return_exceptions=True)

# BROADCAST STATE
async def broadcast_state():
    snapshot = {
        "type": "state",
        "t": now(),
        "players": [{**p, "id": pid, "weapon": p.get("weapon"), "ammo": p.get("ammo")} for pid, p in players.items()],
        "weapons": list(weapons.values()),
        "projectiles": [p for p in projectiles]
    }
    await notify_all(snapshot)

# PHYSICS
async def physics_tick(dt):
    B = 100  # boundary
    for pid, p in players.items():
        if p["health"] <= 0: 
            continue
            
        keys = p.get("keys", {})
        dx = dz = 0
        fwd = rotate_yaw_forward(p["yaw"])
        rgt = rotate_yaw_forward(p["yaw"] + math.pi/2)
        
        # Movement (fixed to match client)
        if keys.get("w"): 
            dx += fwd[0]
            dz += fwd[1]
        if keys.get("s"): 
            dx -= fwd[0]
            dz -= fwd[1]
        if keys.get("a"): 
            dx -= rgt[0]
            dz -= rgt[1]
        if keys.get("d"): 
            dx += rgt[0]
            dz += rgt[1]
            
        # Speed modifiers
        speed = MOVE_SPEED
        if keys.get("shift"):
            speed *= RUN_MULTIPLIER
        if keys.get("ctrl"):
            speed *= CROUCH_MULTIPLIER
            
        L = math.hypot(dx, dz)
        if L > 0: 
            dx = dx/L * speed * dt
            dz = dz/L * speed * dt
            
        p["x"] = max(-B, min(B, p["x"] + dx))
        p["z"] = max(-B, min(B, p["z"] + dz))

# RESPAWN SYSTEM
async def handle_respawn(pid):
    """Respawn a dead player after delay"""
    await asyncio.sleep(RESPAWN_TIME)
    
    if pid in players:
        p = players[pid]
        p["health"] = MAX_HEALTH
        p["weapon"] = None
        p["ammo"] = 0
        
        # Random spawn position
        p["x"] = random.uniform(-50, 50)
        p["z"] = random.uniform(-50, 50)
        p["y"] = 1.0
        
        await notify_player_byid(pid, {
            "type": "respawn",
            "x": p["x"],
            "y": p["y"],
            "z": p["z"]
        })
        
        print(f"[↻] Player {pid} respawned at ({p['x']:.1f}, {p['z']:.1f})")

# HANDLE MESSAGE
async def handle_message(ws, msg):
    pid = clients.get(ws)
    if not pid or pid not in players: 
        return
        
    p = players[pid]
    mtype = msg.get("type")
    
    if mtype == "input":
        inp = msg.get("input", {})
        p["yaw"] = inp.get("yaw", p["yaw"])
        p["pitch"] = inp.get("pitch", p["pitch"])
        p["keys"] = inp.get("keys", p["keys"])
        
    elif mtype == "shoot":
        if p["health"] <= 0:
            return
            
        weapon_name = p.get("weapon")
        if not weapon_name: 
            return
            
        weapon = WEAPON_DATA[weapon_name]
        last_shot = p.get("last_shot", 0)
        
        if now() - last_shot < weapon["fire_rate"]: 
            return
        if p.get("ammo", 0) <= 0: 
            return
            
        p["ammo"] -= 1
        p["last_shot"] = now()
        
        dirv = normalize((msg["dir"]["x"], msg["dir"]["y"], msg["dir"]["z"]))
        
        # Handle shotgun pellets
        if weapon_name == "shotgun":
            for _ in range(weapon.get("pellets", 1)):
                # Add spread for shotgun
                spread = 0.1
                spread_x = dirv[0] + random.uniform(-spread, spread)
                spread_y = dirv[1] + random.uniform(-spread, spread)
                spread_z = dirv[2] + random.uniform(-spread, spread)
                spread_dir = normalize((spread_x, spread_y, spread_z))
                
                projectiles.append({
                    "pos": [p["x"], p["y"] + 0.8, p["z"]],
                    "dir": [spread_dir[0], spread_dir[1], spread_dir[2]],
                    "owner": pid,
                    "type": weapon_name,
                    "time": now()
                })
        else:
            projectiles.append({
                "pos": [p["x"], p["y"] + 0.8, p["z"]],
                "dir": [dirv[0], dirv[1], dirv[2]],
                "owner": pid,
                "type": weapon_name,
                "time": now()
            })
            
    elif mtype == "pickup":
        if p["health"] <= 0:
            return
            
        wid = msg.get("id")
        if wid in weapons:
            wp = weapons.pop(wid)
            p["weapon"] = wp["type"]
            p["ammo"] = WEAPON_DATA[wp["type"]]["mag"]
            
            await notify_player_byid(pid, {
                "type": "weapon_pickup",
                "weapon": wp["type"],
                "ammo": p["ammo"],
                "id": wid
            })
            await notify_all({"type": "weapon_remove", "id": wid})
            print(f"[🔫] Player {pid} picked up {wp['type']}")
            
    elif mtype == "respawn":
        if p["health"] <= 0:
            asyncio.create_task(handle_respawn(pid))

# REGISTER / UNREGISTER
async def register(ws, info):
    pid = str(uuid.uuid4())[:8]
    clients[ws] = pid
    
    # Better spawn distribution
    spawn_x = random.uniform(-50, 50)
    spawn_z = random.uniform(-50, 50)
    
    players[pid] = {
        "id": pid,
        "x": spawn_x,
        "y": 1.0,
        "z": spawn_z,
        "yaw": 0,
        "pitch": 0,
        "health": MAX_HEALTH,
        "keys": {},
        "weapon": None,
        "ammo": 0,
        "kills": 0,
        "deaths": 0
    }
    
    await ws.send(json.dumps({"type": "welcome", "id": pid, "t": now()}))
    await notify_all({"type": "join", "id": pid})
    print(f"[+] Player {pid} joined at ({spawn_x:.1f}, {spawn_z:.1f})")

async def unregister(ws):
    pid = clients.pop(ws, None)
    if pid: 
        players.pop(pid, None)
        await notify_all({"type": "leave", "id": pid})
        print(f"[-] Player {pid} left")

# HANDLER
async def handler(ws):
    try:
        intro = await asyncio.wait_for(ws.recv(), timeout=5)
        try:
            intro_j = json.loads(intro)
        except:
            intro_j = {}
        await register(ws, intro_j)
    except: 
        await register(ws, {})
        
    try:
        async for msg in ws:
            try: 
                msg = json.loads(msg)
            except: 
                continue
            await handle_message(ws, msg)
    except websockets.exceptions.ConnectionClosed: 
        pass
    finally: 
        await unregister(ws)

# WEAPON SPAWN LOOP
async def spawn_weapon_loop():
    while True:
        await asyncio.sleep(WEAPON_SPAWN_INTERVAL)
        if len(weapons) >= WEAPON_MAX: 
            continue
            
        wid = str(uuid.uuid4())[:8]
        wtype = random.choice(list(WEAPON_DATA.keys()))
        
        weapons[wid] = {
            "id": wid,
            "type": wtype,
            "x": random.uniform(-80, 80),
            "y": 1.0,
            "z": random.uniform(-80, 80)
        }
        
        await notify_all({"type": "weapon_spawn", **weapons[wid]})
        print(f"[🔫] Spawned {wtype} at ({weapons[wid]['x']:.1f}, {weapons[wid]['z']:.1f})")

# PROJECTILE LOOP
async def projectile_loop(dt):
    speed = 50.0
    while True:
        remove = []
        
        for proj in projectiles:
            # Move projectile
            proj["pos"][0] += proj["dir"][0] * speed * dt
            proj["pos"][1] += proj["dir"][1] * speed * dt
            proj["pos"][2] += proj["dir"][2] * speed * dt
            
            # Check collision with players
            hit = False
            for oid, op in players.items():
                if oid == proj["owner"] or op["health"] <= 0: 
                    continue
                    
                dx = op["x"] - proj["pos"][0]
                dy = op["y"] - proj["pos"][1]
                dz = op["z"] - proj["pos"][2]
                
                if math.sqrt(dx*dx + dy*dy + dz*dz) < 1.0:
                    damage = WEAPON_DATA[proj["type"]]["damage"]
                    op["health"] = max(0, op["health"] - damage)
                    
                    await notify_player_byid(oid, {
                        "type": "got_hit",
                        "by": proj["owner"],
                        "health": op["health"]
                    })
                    
                    await notify_player_byid(proj["owner"], {
                        "type": "hit",
                        "target": oid,
                        "by": proj["owner"],
                        "health": op["health"]
                    })
                    
                    # Handle kill
                    if op["health"] == 0:
                        op["deaths"] = op.get("deaths", 0) + 1
                        
                        if proj["owner"] in players:
                            players[proj["owner"]]["kills"] = players[proj["owner"]].get("kills", 0) + 1
                        
                        await notify_all({
                            "type": "kill",
                            "killer": proj["owner"],
                            "victim": oid
                        })
                        
                        print(f"[☠️] {proj['owner']} killed {oid}")
                        
                        # Auto respawn after delay
                        asyncio.create_task(handle_respawn(oid))
                    
                    remove.append(proj)
                    hit = True
                    break
            
            # Remove old projectiles
            if not hit and now() - proj["time"] > 2.0: 
                remove.append(proj)
        
        for r in remove: 
            if r in projectiles:
                projectiles.remove(r)
                
        await asyncio.sleep(dt)

# MAIN LOOP
async def main_loop():
    dt = 1.0/TICK_RATE
    while True:
        await physics_tick(dt)
        await asyncio.sleep(dt)

async def broadcaster_loop():
    dt = 1.0/BROADCAST_RATE
    while True:
        await broadcast_state()
        await asyncio.sleep(dt)

# START SERVER
if __name__ == "__main__":
    async def main():
        print("=" * 60)
        print("🎮 MULTIPLAYER FPS SERVER")
        print("=" * 60)
        print(f"📡 Starting server on ws://0.0.0.0:8765")
        print(f"⚙️  Tick Rate: {TICK_RATE} Hz")
        print(f"📤 Broadcast Rate: {BROADCAST_RATE} Hz")
        print(f"🔫 Weapons: {', '.join(WEAPON_DATA.keys())}")
        print(f"💀 Respawn Time: {RESPAWN_TIME}s")
        print("=" * 60)
        
        async with websockets.serve(handler, "0.0.0.0", 8765, ping_interval=None):
            asyncio.create_task(main_loop())
            asyncio.create_task(broadcaster_loop())
            asyncio.create_task(spawn_weapon_loop())
            asyncio.create_task(projectile_loop(1.0/TICK_RATE))
            
            print("✅ Server is running! Waiting for players...")
            print("Press Ctrl+C to stop")
            print()
            
            await asyncio.Future()
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
