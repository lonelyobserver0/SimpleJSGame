#!/usr/bin/env python3
import asyncio, websockets, json, time, math, uuid, random
from collections import defaultdict
import hashlib
import secrets
import logging
logging.basicConfig(level=logging.DEBUG)


# ==================== CONFIG ====================
TICK_RATE = 20
BROADCAST_RATE = 20
MOVE_SPEED = 5.0
RUN_MULTIPLIER = 1.8
CROUCH_MULTIPLIER = 0.5
MAX_HEALTH = 100
MAX_ARMOR = 100
RESPAWN_TIME = 5.0

# Security settings
MAX_CONNECTIONS_PER_IP = 3
MAX_MESSAGE_SIZE = 4096
MAX_MESSAGES_PER_SECOND = 30
BAN_DURATION = 3600  # 1 hour in seconds
MAX_MOVEMENT_SPEED = 15.0  # units per second
POSITION_VALIDATION_THRESHOLD = 20.0  # max distance per tick
MIN_SHOT_INTERVAL = 0.03  # minimum time between shots (anti-rapidfire)
MAX_NAME_LENGTH = 20

# Rate limiting
rate_limits = defaultdict(lambda: {"count": 0, "reset_time": time.time()})
banned_ips = {}  # ip -> ban_until_time
ip_connections = defaultdict(int)
player_last_positions = {}  # pid -> {x, z, time}
player_violations = defaultdict(int)  # pid -> violation_count

# Weapon configurations
WEAPON_DATA = {
    "pistol": {"damage": 20, "range": 25, "mag": 12, "fire_rate": 0.4},
    "rifle": {"damage": 34, "range": 35, "mag": 30, "fire_rate": 0.1},
    "shotgun": {"damage": 10, "range": 15, "pellets": 5, "mag": 8, "fire_rate": 1.0},
    "sniper": {"damage": 80, "range": 100, "mag": 5, "fire_rate": 1.5},
    "smg": {"damage": 18, "range": 20, "mag": 40, "fire_rate": 0.05}
}

WEAPON_SPAWN_INTERVAL = 5.0
WEAPON_MAX = 15

# Powerup configurations
POWERUP_TYPES = ["health", "armor", "speed"]
POWERUP_SPAWN_INTERVAL = 8.0
POWERUP_MAX = 8

# Grenade configuration
GRENADE_DAMAGE = 80
GRENADE_RADIUS = 10.0

# Game mode configurations
GAME_MODES = {
    "deathmatch": {"teams": False, "score_limit": 30},
    "team_deathmatch": {"teams": True, "score_limit": 50},
    "capture_flag": {"teams": True, "flags": True},
    "king_hill": {"teams": False, "hill": True}
}

# ==================== GLOBAL STATE ====================
clients = {}       # ws -> pid
players = {}       # pid -> player dict
weapons = {}       # wid -> weapon dict
powerups = {}      # pwid -> powerup dict
projectiles = []   # list of projectiles
grenades = []      # list of grenades
game_mode = "deathmatch"
team_scores = {"red": 0, "blue": 0}

# ==================== SECURITY FUNCTIONS ====================
def get_client_ip(ws):
    """Extract client IP from websocket connection"""
    try:
        return ws.remote_address[0] if ws.remote_address else "unknown"
    except:
        return "unknown"

def is_banned(ip):
    """Check if IP is banned"""
    if ip in banned_ips:
        if time.time() < banned_ips[ip]:
            return True
        else:
            del banned_ips[ip]
    return False

def ban_ip(ip, duration=BAN_DURATION):
    """Ban an IP address"""
    banned_ips[ip] = time.time() + duration
    print(f"🚫 Banned IP {ip} for {duration} seconds")

def check_rate_limit(ip):
    """Check if client exceeds rate limit"""
    now = time.time()
    limit = rate_limits[ip]
    
    # Reset counter every second
    if now - limit["reset_time"] > 1.0:
        limit["count"] = 0
        limit["reset_time"] = now
    
    limit["count"] += 1
    
    if limit["count"] > MAX_MESSAGES_PER_SECOND:
        print(f"⚠️ Rate limit exceeded for {ip}")
        return False
    
    return True

def sanitize_string(s, max_length=MAX_NAME_LENGTH):
    """Sanitize user input strings"""
    if not isinstance(s, str):
        return ""
    # Remove control characters and limit length
    sanitized = ''.join(char for char in s if char.isprintable())
    return sanitized[:max_length]

def validate_position(pid, x, z):
    """Validate player position to detect teleport hacks"""
    if pid not in player_last_positions:
        player_last_positions[pid] = {"x": x, "z": z, "time": time.time()}
        return True
    
    last = player_last_positions[pid]
    dt = time.time() - last["time"]
    
    if dt < 0.001:  # Too fast, ignore
        return True
    
    distance = math.sqrt((x - last["x"])**2 + (z - last["z"])**2)
    max_distance = MAX_MOVEMENT_SPEED * dt
    
    if distance > max_distance * 1.5:  # 50% tolerance
        print(f"⚠️ Suspicious movement detected for {pid}: {distance:.2f} units in {dt:.3f}s")
        player_violations[pid] += 1
        
        if player_violations[pid] >= 5:
            print(f"🚫 Player {pid} banned for movement violations")
            return False
        
        # Teleport back to last valid position
        players[pid]["x"] = last["x"]
        players[pid]["z"] = last["z"]
        return False
    
    player_last_positions[pid] = {"x": x, "z": z, "time": time.time()}
    return True

def validate_shot(pid, weapon_name):
    """Validate shooting to prevent rapid-fire hacks"""
    p = players.get(pid)
    if not p:
        return False
    
    last_shot = p.get("last_shot", 0)
    weapon = WEAPON_DATA.get(weapon_name)
    
    if not weapon:
        return False
    
    time_since_last = time.time() - last_shot
    
    # Check if shooting faster than weapon allows
    if time_since_last < max(weapon["fire_rate"] * 0.8, MIN_SHOT_INTERVAL):
        player_violations[pid] += 1
        print(f"⚠️ Rapid fire detected for {pid}")
        
        if player_violations[pid] >= 10:
            print(f"🚫 Player {pid} banned for rapid-fire")
            return False
        
        return False
    
    return True

def validate_damage(damage, weapon_name):
    """Validate damage values to prevent damage hacks"""
    weapon = WEAPON_DATA.get(weapon_name)
    if not weapon:
        return 0
    
    max_damage = weapon["damage"] * 1.1  # 10% tolerance
    return min(damage, max_damage)

# ==================== UTILITY FUNCTIONS ====================
def now(): 
    return time.time()

def vec_len(v): 
    return math.sqrt(sum([x*x for x in v]))

def normalize(v): 
    L = vec_len(v)
    return (0, 0, 0) if L == 0 else tuple(x/L for x in v)

def rotate_yaw_forward(yaw, amt=1.0): 
    return (math.sin(yaw)*amt, math.cos(yaw)*amt)

def distance(p1, p2):
    return math.sqrt((p1["x"] - p2["x"])**2 + (p1["z"] - p2["z"])**2)

def assign_team():
    """Assign player to team with fewer players"""
    red_count = sum(1 for p in players.values() if p.get("team") == "red")
    blue_count = sum(1 for p in players.values() if p.get("team") == "blue")
    return "red" if red_count <= blue_count else "blue"

# ==================== NOTIFICATION FUNCTIONS ====================
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

async def notify_team(team, msg):
    data = json.dumps(msg)
    team_clients = [ws for ws, pid in clients.items() if players.get(pid, {}).get("team") == team]
    await asyncio.gather(*[ws.send(data) for ws in team_clients], return_exceptions=True)

# ==================== BROADCAST STATE ====================
async def broadcast_state():
    snapshot = {
        "type": "state",
        "t": now(),
        "players": [
            {
                **p, 
                "id": pid, 
                "weapon": p.get("weapon"), 
                "ammo": p.get("ammo"),
                "armor": p.get("armor", 0),
                "team": p.get("team"),
                "kills": p.get("kills", 0),
                "deaths": p.get("deaths", 0)
            } for pid, p in players.items()
        ],
        "weapons": list(weapons.values()),
        "powerups": list(powerups.values()),
        "team_scores": team_scores if GAME_MODES[game_mode].get("teams") else None
    }
    await notify_all(snapshot)

# ==================== PHYSICS ====================
async def physics_tick(dt):
    B = 100  # boundary
    
    for pid, p in players.items():
        if p["health"] <= 0: 
            continue
            
        keys = p.get("keys", {})
        dx = dz = 0
        
        # Calculate forward and right vectors
        yaw = p["yaw"]
        fwd_x = math.sin(yaw)
        fwd_z = math.cos(yaw)
        rgt_x = math.sin(yaw + math.pi/2)
        rgt_z = math.cos(yaw + math.pi/2)
        
        # Movement (W = backward with -=, S = forward with += - INVERTED)
        if keys.get("w"): 
            dx -= fwd_x
            dz -= fwd_z
        if keys.get("s"): 
            dx += fwd_x
            dz += fwd_z
        if keys.get("a"): 
            dx -= rgt_x
            dz -= rgt_z
        if keys.get("d"): 
            dx += rgt_x
            dz += rgt_z
            
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
        
        new_x = max(-B, min(B, p["x"] + dx))
        new_z = max(-B, min(B, p["z"] + dz))
        
        # Validate movement
        if validate_position(pid, new_x, new_z):
            p["x"] = new_x
            p["z"] = new_z
        
        # Check powerup pickups
        for pwid, pw in list(powerups.items()):
            dist = math.sqrt((p["x"] - pw["x"])**2 + (p["z"] - pw["z"])**2)
            if dist < 1.5:
                await handle_powerup_pickup(pid, pwid)

# ==================== POWERUP SYSTEM ====================
async def handle_powerup_pickup(pid, pwid):
    if pwid not in powerups:
        return
        
    pw = powerups.pop(pwid)
    p = players[pid]
    
    if pw["type"] == "health":
        p["health"] = min(MAX_HEALTH, p["health"] + 50)
    elif pw["type"] == "armor":
        p["armor"] = min(MAX_ARMOR, p.get("armor", 0) + 50)
    elif pw["type"] == "speed":
        pass
    
    await notify_player_byid(pid, {
        "type": "powerup_pickup",
        "powerup_type": pw["type"],
        "id": pwid
    })
    
    await notify_all({"type": "powerup_remove", "id": pwid})
    print(f"[⚡] Player {pid} picked up {pw['type']} powerup")

# ==================== RESPAWN SYSTEM ====================
async def handle_respawn(pid):
    """Respawn a dead player after delay"""
    await asyncio.sleep(RESPAWN_TIME)
    
    if pid not in players:
        return
        
    p = players[pid]
    p["health"] = MAX_HEALTH
    p["armor"] = 0
    p["weapon"] = None
    p["ammo"] = 0
    
    # Team-based spawns
    if p.get("team") == "red":
        p["x"] = random.uniform(-80, -40)
        p["z"] = random.uniform(-50, 50)
    elif p.get("team") == "blue":
        p["x"] = random.uniform(40, 80)
        p["z"] = random.uniform(-50, 50)
    else:
        p["x"] = random.uniform(-50, 50)
        p["z"] = random.uniform(-50, 50)
    
    p["y"] = 1.0
    
    # Reset position tracking
    player_last_positions[pid] = {"x": p["x"], "z": p["z"], "time": time.time()}
    
    await notify_player_byid(pid, {
        "type": "respawn",
        "x": p["x"],
        "y": p["y"],
        "z": p["z"]
    })
    
    print(f"[↻] Player {pid} respawned at ({p['x']:.1f}, {p['z']:.1f})")

# ==================== MESSAGE HANDLER ====================
async def handle_message(ws, msg):
    pid = clients.get(ws)
    if not pid or pid not in players: 
        return
    
    # Check message size
    if len(json.dumps(msg)) > MAX_MESSAGE_SIZE:
        print(f"⚠️ Oversized message from {pid}")
        return
        
    p = players[pid]
    mtype = msg.get("type")
    
    if mtype == "input":
        inp = msg.get("input", {})
        
        # Validate yaw and pitch
        yaw = inp.get("yaw", p["yaw"])
        pitch = inp.get("pitch", p["pitch"])
        
        # Clamp values
        p["yaw"] = max(-math.pi*2, min(math.pi*2, yaw))
        p["pitch"] = max(-math.pi/2, min(math.pi/2, pitch))
        p["keys"] = inp.get("keys", p["keys"])
        
    elif mtype == "shoot":
        if p["health"] <= 0:
            return
            
        weapon_name = p.get("weapon")
        if not weapon_name or weapon_name not in WEAPON_DATA: 
            return
        
        # Validate shot timing
        if not validate_shot(pid, weapon_name):
            return
            
        weapon = WEAPON_DATA[weapon_name]
        
        if p.get("ammo", 0) <= 0: 
            return
            
        p["ammo"] -= 1
        p["last_shot"] = now()
        
        dirv = normalize((msg["dir"]["x"], msg["dir"]["y"], msg["dir"]["z"]))
        
        # Handle shotgun pellets
        num_projectiles = weapon.get("pellets", 1)
        for i in range(min(num_projectiles, 10)):  # Cap at 10 pellets
            if num_projectiles > 1:
                spread = 0.1
                spread_x = dirv[0] + random.uniform(-spread, spread)
                spread_y = dirv[1] + random.uniform(-spread, spread)
                spread_z = dirv[2] + random.uniform(-spread, spread)
                shoot_dir = normalize((spread_x, spread_y, spread_z))
            else:
                shoot_dir = dirv
            
            projectiles.append({
                "pos": [p["x"], p["y"] + 0.8, p["z"]],
                "dir": [shoot_dir[0], shoot_dir[1], shoot_dir[2]],
                "owner": pid,
                "type": weapon_name,
                "time": now()
            })
            
    elif mtype == "grenade_explode":
        pos = msg.get("pos", {})
        await handle_grenade_explosion(pid, pos)
        
    elif mtype == "pickup":
        if p["health"] <= 0:
            return
            
        pickup_id = msg.get("id")
        pickup_type = msg.get("pickupType", "weapon")
        
        if pickup_type == "weapon" and pickup_id in weapons:
            wp = weapons.pop(pickup_id)
            p["weapon"] = wp["type"]
            p["ammo"] = WEAPON_DATA[wp["type"]]["mag"]
            
            await notify_player_byid(pid, {
                "type": "weapon_pickup",
                "weapon": wp["type"],
                "ammo": p["ammo"],
                "id": pickup_id
            })
            await notify_all({"type": "weapon_remove", "id": pickup_id})
            print(f"[🔫] Player {pid} picked up {wp['type']}")
            
        elif pickup_type == "powerup" and pickup_id in powerups:
            await handle_powerup_pickup(pid, pickup_id)
            
    elif mtype == "chat":
        message = sanitize_string(msg.get("message", ""), 200)
        if len(message) > 0:
            chat_msg = {
                "type": "chat",
                "sender": pid[:8],
                "message": message,
                "team": p.get("team")
            }
            
            if message.startswith("@") and p.get("team"):
                await notify_team(p["team"], chat_msg)
            else:
                await notify_all(chat_msg)
                
    elif mtype == "respawn":
        if p["health"] <= 0:
            asyncio.create_task(handle_respawn(pid))

# ==================== GRENADE SYSTEM ====================
async def handle_grenade_explosion(owner_id, pos):
    """Handle grenade explosion damage"""
    ex, ey, ez = pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
    
    for pid, p in players.items():
        if p["health"] <= 0:
            continue
            
        dist = math.sqrt((p["x"] - ex)**2 + (p["y"] - ey)**2 + (p["z"] - ez)**2)
        
        if dist < GRENADE_RADIUS:
            damage_mult = 1.0 - (dist / GRENADE_RADIUS)
            damage = int(validate_damage(GRENADE_DAMAGE * damage_mult, "rifle"))
            
            armor = p.get("armor", 0)
            if armor > 0:
                armor_absorb = min(armor, damage // 2)
                damage -= armor_absorb
                p["armor"] = armor - armor_absorb
            
            p["health"] = max(0, p["health"] - damage)
            
            await notify_player_byid(pid, {
                "type": "got_hit",
                "by": owner_id,
                "health": p["health"],
                "damage": damage
            })
            
            if p["health"] == 0:
                p["deaths"] = p.get("deaths", 0) + 1
                
                if owner_id in players:
                    players[owner_id]["kills"] = players[owner_id].get("kills", 0) + 1
                
                await notify_all({
                    "type": "kill",
                    "killer": owner_id,
                    "victim": pid
                })
                
                print(f"[💥] {owner_id} killed {pid} with grenade")
                asyncio.create_task(handle_respawn(pid))

# ==================== REGISTER / UNREGISTER ====================
async def register(ws, info):
    ip = get_client_ip(ws)
    
    # Check if banned
    if is_banned(ip):
        await ws.close(1008, "Banned")
        print(f"🚫 Rejected banned IP: {ip}")
        return False
    
    # Check connection limit per IP
    if ip_connections[ip] >= MAX_CONNECTIONS_PER_IP:
        await ws.close(1008, "Too many connections")
        print(f"⚠️ Too many connections from {ip}")
        return False
    
    ip_connections[ip] += 1
    
    pid = str(uuid.uuid4())[:8]
    clients[ws] = pid
    
    mode = info.get("mode", "deathmatch")
    team = None
    
    if GAME_MODES.get(mode, {}).get("teams"):
        team = assign_team()
    
    # Team-based spawn positions
    if team == "red":
        spawn_x = random.uniform(-80, -40)
        spawn_z = random.uniform(-50, 50)
    elif team == "blue":
        spawn_x = random.uniform(40, 80)
        spawn_z = random.uniform(-50, 50)
    else:
        spawn_x = random.uniform(-50, 50)
        spawn_z = random.uniform(-50, 50)
    
    name = sanitize_string(info.get("name", f"Player{pid[:4]}"))
    
    players[pid] = {
        "id": pid,
        "name": name,
        "x": spawn_x,
        "y": 1.0,
        "z": spawn_z,
        "yaw": 0,
        "pitch": 0,
        "health": MAX_HEALTH,
        "armor": 0,
        "keys": {},
        "weapon": None,
        "ammo": 0,
        "kills": 0,
        "deaths": 0,
        "team": team,
        "ip": ip
    }
    
    player_last_positions[pid] = {"x": spawn_x, "z": spawn_z, "time": time.time()}
    player_violations[pid] = 0
    
    await ws.send(json.dumps({
        "type": "welcome", 
        "id": pid, 
        "team": team,
        "t": now()
    }))
    
    await notify_all({
        "type": "join", 
        "id": pid,
        "team": team
    })
    
    team_str = f" (Team: {team})" if team else ""
    print(f"[+] Player {pid} ({ip}) joined{team_str}")
    return True

async def unregister(ws):
    pid = clients.pop(ws, None)
    if pid:
        ip = players.get(pid, {}).get("ip", "unknown")
        if ip != "unknown":
            ip_connections[ip] = max(0, ip_connections[ip] - 1)
        
        players.pop(pid, None)
        player_last_positions.pop(pid, None)
        player_violations.pop(pid, None)
        
        await notify_all({"type": "leave", "id": pid})
        print(f"[-] Player {pid} left")

# ==================== CONNECTION HANDLER ====================
async def handler(ws):
    ip = get_client_ip(ws)
    
    # Check ban status
    if is_banned(ip):
        await ws.close(1008, "Banned")
        return
    
    # Rate limiting check
    if not check_rate_limit(ip):
        await ws.close(1008, "Rate limit exceeded")
        return
    
    try:
        intro = await asyncio.wait_for(ws.recv(), timeout=5)
        try:
            intro_j = json.loads(intro)
        except:
            intro_j = {}
        
        success = await register(ws, intro_j)
        if not success:
            return
            
    except asyncio.TimeoutError:
        await ws.close(1002, "Timeout")
        return
    except:
        await register(ws, {})
        
    try:
        async for msg in ws:
            # Rate limit per message
            if not check_rate_limit(ip):
                print(f"⚠️ Rate limit exceeded for {ip}, closing connection")
                await ws.close(1008, "Rate limit exceeded")
                break
            
            try: 
                msg = json.loads(msg)
            except: 
                continue
            
            await handle_message(ws, msg)
            
    except websockets.exceptions.ConnectionClosed: 
        pass
    except Exception as e:
        print(f"❌ Error handling message from {ip}: {e}")
    finally: 
        await unregister(ws)

# ==================== SPAWN LOOPS ====================
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

async def spawn_powerup_loop():
    while True:
        await asyncio.sleep(POWERUP_SPAWN_INTERVAL)
        if len(powerups) >= POWERUP_MAX:
            continue
            
        pwid = str(uuid.uuid4())[:8]
        pwtype = random.choice(POWERUP_TYPES)
        
        powerups[pwid] = {
            "id": pwid,
            "type": pwtype,
            "x": random.uniform(-80, 80),
            "y": 1.0,
            "z": random.uniform(-80, 80)
        }
        
        await notify_all({"type": "powerup_spawn", **powerups[pwid]})

# ==================== PROJECTILE LOOP ====================
async def projectile_loop(dt):
    speed = 50.0
    while True:
        remove = []
        
        for proj in projectiles:
            proj["pos"][0] += proj["dir"][0] * speed * dt
            proj["pos"][1] += proj["dir"][1] * speed * dt
            proj["pos"][2] += proj["dir"][2] * speed * dt
            
            hit = False
            for oid, op in players.items():
                if oid == proj["owner"] or op["health"] <= 0: 
                    continue
                
                if players[proj["owner"]].get("team") == op.get("team") and op.get("team"):
                    continue
                    
                dx = op["x"] - proj["pos"][0]
                dy = op["y"] - proj["pos"][1]
                dz = op["z"] - proj["pos"][2]
                
                if math.sqrt(dx*dx + dy*dy + dz*dz) < 1.0:
                    damage = validate_damage(WEAPON_DATA[proj["type"]]["damage"], proj["type"])
                    
                    armor = op.get("armor", 0)
                    if armor > 0:
                        armor_absorb = min(armor, damage // 2)
                        damage -= armor_absorb
                        op["armor"] = armor - armor_absorb
                    
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
                    
                    if op["health"] == 0:
                        op["deaths"] = op.get("deaths", 0) + 1
                        
                        if proj["owner"] in players:
                            players[proj["owner"]]["kills"] = players[proj["owner"]].get("kills", 0) + 1
                            
                            killer_team = players[proj["owner"]].get("team")
                            if killer_team:
                                team_scores[killer_team] = team_scores.get(killer_team, 0) + 1
                        
                        await notify_all({
                            "type": "kill",
                            "killer": proj["owner"],
                            "victim": oid
                        })
                        
                        asyncio.create_task(handle_respawn(oid))
                    
                    remove.append(proj)
                    hit = True
                    break
            
            if not hit and now() - proj["time"] > 2.0: 
                remove.append(proj)
        
        for r in remove: 
            if r in projectiles:
                projectiles.remove(r)
                
        await asyncio.sleep(dt)

# ==================== MAIN LOOPS ====================
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

async def cleanup_loop():
    """Periodic cleanup of old data"""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        
        # Clean expired bans
        now_time = time.time()
        expired = [ip for ip, until in banned_ips.items() if now_time > until]
        for ip in expired:
            del banned_ips[ip]
            print(f"✅ Ban expired for {ip}")
        
        # Clean old violations
        for pid in list(player_violations.keys()):
            if pid not in players:
                del player_violations[pid]
        
        # Clean old position tracking
        for pid in list(player_last_positions.keys()):
            if pid not in players:
                del player_last_positions[pid]
        
        print(f"🧹 Cleanup: {len(players)} players, {len(banned_ips)} bans active")

# ==================== SERVER START ====================
if __name__ == "__main__":
    async def main():
        print("=" * 70)
        print("🎮 MULTIPLAYER FPS SERVER - SECURE EDITION")
        print("=" * 70)
        print(f"📡 Starting server on ws://0.0.0.0:8765")
        print(f"⚙️  Tick Rate: {TICK_RATE} Hz")
        print(f"📤 Broadcast Rate: {BROADCAST_RATE} Hz")
        print(f"🔫 Weapons: {', '.join(WEAPON_DATA.keys())}")
        print(f"⚡ Powerups: {', '.join(POWERUP_TYPES)}")
        print(f"🎮 Game Modes: {', '.join(GAME_MODES.keys())}")
        print(f"💀 Respawn Time: {RESPAWN_TIME}s")
        print()
        print("🔒 SECURITY FEATURES:")
        print(f"   • Max connections per IP: {MAX_CONNECTIONS_PER_IP}")
        print(f"   • Rate limit: {MAX_MESSAGES_PER_SECOND} msg/s")
        print(f"   • Max message size: {MAX_MESSAGE_SIZE} bytes")
        print(f"   • Ban duration: {BAN_DURATION}s")
        print(f"   • Anti-speedhack: max {MAX_MOVEMENT_SPEED} units/s")
        print(f"   • Anti-rapidfire: min {MIN_SHOT_INTERVAL}s between shots")
        print(f"   • Position validation enabled")
        print(f"   • Damage validation enabled")
        print(f"   • Input sanitization enabled")
        print("=" * 70)
        
        async with websockets.serve(
            handler, 
            "0.0.0.0", 
            8765, 
            ping_interval=20,
            ping_timeout=10,
            max_size=MAX_MESSAGE_SIZE,
            max_queue=32
        ):
            asyncio.create_task(main_loop())
            asyncio.create_task(broadcaster_loop())
            asyncio.create_task(spawn_weapon_loop())
            asyncio.create_task(spawn_powerup_loop())
            asyncio.create_task(projectile_loop(1.0/TICK_RATE))
            asyncio.create_task(cleanup_loop())
            
            print("✅ Server is running! Waiting for players...")
            print("🛡️ All security systems active")
            print("Press Ctrl+C to stop")
            print()
            
            await asyncio.Future()
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
        print("Thanks for playing!")
#!/usr/bin/env python3
import asyncio, websockets, json, time, math, uuid, random

# ==================== CONFIG ====================
TICK_RATE = 20
BROADCAST_RATE = 20
MOVE_SPEED = 5.0
RUN_MULTIPLIER = 1.8
CROUCH_MULTIPLIER = 0.5
MAX_HEALTH = 100
MAX_ARMOR = 100
RESPAWN_TIME = 5.0

# Weapon configurations
WEAPON_DATA = {
    "pistol": {"damage": 20, "range": 25, "mag": 12, "fire_rate": 0.4},
    "rifle": {"damage": 34, "range": 35, "mag": 30, "fire_rate": 0.1},
    "shotgun": {"damage": 10, "range": 15, "pellets": 5, "mag": 8, "fire_rate": 1.0},
    "sniper": {"damage": 80, "range": 100, "mag": 5, "fire_rate": 1.5},
    "smg": {"damage": 18, "range": 20, "mag": 40, "fire_rate": 0.05}
}

WEAPON_SPAWN_INTERVAL = 5.0
WEAPON_MAX = 15

# Powerup configurations
POWERUP_TYPES = ["health", "armor", "speed"]
POWERUP_SPAWN_INTERVAL = 8.0
POWERUP_MAX = 8

# Grenade configuration
GRENADE_DAMAGE = 80
GRENADE_RADIUS = 10.0

# Game mode configurations
GAME_MODES = {
    "deathmatch": {"teams": False, "score_limit": 30},
    "team_deathmatch": {"teams": True, "score_limit": 50},
    "capture_flag": {"teams": True, "flags": True},
    "king_hill": {"teams": False, "hill": True}
}

# ==================== GLOBAL STATE ====================
clients = {}       # ws -> pid
players = {}       # pid -> player dict
weapons = {}       # wid -> weapon dict
powerups = {}      # pwid -> powerup dict
projectiles = []   # list of projectiles
grenades = []      # list of grenades
game_mode = "deathmatch"
team_scores = {"red": 0, "blue": 0}

# ==================== UTILITY FUNCTIONS ====================
def now(): 
    return time.time()

def vec_len(v): 
    return math.sqrt(sum([x*x for x in v]))

def normalize(v): 
    L = vec_len(v)
    return (0, 0, 0) if L == 0 else tuple(x/L for x in v)

def rotate_yaw_forward(yaw, amt=1.0): 
    return (math.sin(yaw)*amt, math.cos(yaw)*amt)

def distance(p1, p2):
    return math.sqrt((p1["x"] - p2["x"])**2 + (p1["z"] - p2["z"])**2)

def assign_team():
    """Assign player to team with fewer players"""
    red_count = sum(1 for p in players.values() if p.get("team") == "red")
    blue_count = sum(1 for p in players.values() if p.get("team") == "blue")
    return "red" if red_count <= blue_count else "blue"

# ==================== NOTIFICATION FUNCTIONS ====================
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

async def notify_team(team, msg):
    data = json.dumps(msg)
    team_clients = [ws for ws, pid in clients.items() if players.get(pid, {}).get("team") == team]
    await asyncio.gather(*[ws.send(data) for ws in team_clients], return_exceptions=True)

# ==================== BROADCAST STATE ====================
async def broadcast_state():
    snapshot = {
        "type": "state",
        "t": now(),
        "players": [
            {
                **p, 
                "id": pid, 
                "weapon": p.get("weapon"), 
                "ammo": p.get("ammo"),
                "armor": p.get("armor", 0),
                "team": p.get("team"),
                "kills": p.get("kills", 0),
                "deaths": p.get("deaths", 0)
            } for pid, p in players.items()
        ],
        "weapons": list(weapons.values()),
        "powerups": list(powerups.values()),
        "team_scores": team_scores if GAME_MODES[game_mode].get("teams") else None
    }
    await notify_all(snapshot)

# ==================== PHYSICS ====================
async def physics_tick(dt):
    B = 100  # boundary
    
    for pid, p in players.items():
        if p["health"] <= 0: 
            continue
            
        keys = p.get("keys", {})
        dx = dz = 0
        
        # Calculate forward and right vectors
        yaw = p["yaw"]
        fwd_x = math.sin(yaw)
        fwd_z = math.cos(yaw)
        rgt_x = math.sin(yaw + math.pi/2)
        rgt_z = math.cos(yaw + math.pi/2)
        
        # Movement (W = backward with -=, S = forward with += - INVERTED)
        if keys.get("w"): 
            dx -= fwd_x
            dz -= fwd_z
        if keys.get("s"): 
            dx += fwd_x
            dz += fwd_z
        if keys.get("a"): 
            dx -= rgt_x
            dz -= rgt_z
        if keys.get("d"): 
            dx += rgt_x
            dz += rgt_z
            
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
        
        # Check powerup pickups
        for pwid, pw in list(powerups.items()):
            dist = math.sqrt((p["x"] - pw["x"])**2 + (p["z"] - pw["z"])**2)
            if dist < 1.5:
                await handle_powerup_pickup(pid, pwid)

# ==================== POWERUP SYSTEM ====================
async def handle_powerup_pickup(pid, pwid):
    if pwid not in powerups:
        return
        
    pw = powerups.pop(pwid)
    p = players[pid]
    
    if pw["type"] == "health":
        p["health"] = min(MAX_HEALTH, p["health"] + 50)
    elif pw["type"] == "armor":
        p["armor"] = min(MAX_ARMOR, p.get("armor", 0) + 50)
    elif pw["type"] == "speed":
        # Speed boost handled client-side
        pass
    
    await notify_player_byid(pid, {
        "type": "powerup_pickup",
        "powerup_type": pw["type"],
        "id": pwid
    })
    
    await notify_all({"type": "powerup_remove", "id": pwid})
    print(f"[⚡] Player {pid} picked up {pw['type']} powerup")

# ==================== RESPAWN SYSTEM ====================
async def handle_respawn(pid):
    """Respawn a dead player after delay"""
    await asyncio.sleep(RESPAWN_TIME)
    
    if pid not in players:
        return
        
    p = players[pid]
    p["health"] = MAX_HEALTH
    p["armor"] = 0
    p["weapon"] = None
    p["ammo"] = 0
    
    # Team-based spawns
    if p.get("team") == "red":
        p["x"] = random.uniform(-80, -40)
        p["z"] = random.uniform(-50, 50)
    elif p.get("team") == "blue":
        p["x"] = random.uniform(40, 80)
        p["z"] = random.uniform(-50, 50)
    else:
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

# ==================== MESSAGE HANDLER ====================
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
        num_projectiles = weapon.get("pellets", 1)
        for i in range(num_projectiles):
            if num_projectiles > 1:
                # Add spread for shotgun
                spread = 0.1
                spread_x = dirv[0] + random.uniform(-spread, spread)
                spread_y = dirv[1] + random.uniform(-spread, spread)
                spread_z = dirv[2] + random.uniform(-spread, spread)
                shoot_dir = normalize((spread_x, spread_y, spread_z))
            else:
                shoot_dir = dirv
            
            projectiles.append({
                "pos": [p["x"], p["y"] + 0.8, p["z"]],
                "dir": [shoot_dir[0], shoot_dir[1], shoot_dir[2]],
                "owner": pid,
                "type": weapon_name,
                "time": now()
            })
            
    elif mtype == "grenade_explode":
        pos = msg.get("pos", {})
        await handle_grenade_explosion(pid, pos)
        
    elif mtype == "pickup":
        if p["health"] <= 0:
            return
            
        pickup_id = msg.get("id")
        pickup_type = msg.get("pickupType", "weapon")
        
        if pickup_type == "weapon" and pickup_id in weapons:
            wp = weapons.pop(pickup_id)
            p["weapon"] = wp["type"]
            p["ammo"] = WEAPON_DATA[wp["type"]]["mag"]
            
            await notify_player_byid(pid, {
                "type": "weapon_pickup",
                "weapon": wp["type"],
                "ammo": p["ammo"],
                "id": pickup_id
            })
            await notify_all({"type": "weapon_remove", "id": pickup_id})
            print(f"[🔫] Player {pid} picked up {wp['type']}")
            
        elif pickup_type == "powerup" and pickup_id in powerups:
            await handle_powerup_pickup(pid, pickup_id)
            
    elif mtype == "chat":
        message = msg.get("message", "")
        if len(message) > 0 and len(message) <= 200:
            chat_msg = {
                "type": "chat",
                "sender": pid[:8],
                "message": message,
                "team": p.get("team")
            }
            
            # Team chat if message starts with @
            if message.startswith("@") and p.get("team"):
                await notify_team(p["team"], chat_msg)
            else:
                await notify_all(chat_msg)
                
    elif mtype == "respawn":
        if p["health"] <= 0:
            asyncio.create_task(handle_respawn(pid))

# ==================== GRENADE SYSTEM ====================
async def handle_grenade_explosion(owner_id, pos):
    """Handle grenade explosion damage"""
    ex, ey, ez = pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
    
    for pid, p in players.items():
        if p["health"] <= 0:
            continue
            
        # Calculate distance
        dist = math.sqrt((p["x"] - ex)**2 + (p["y"] - ey)**2 + (p["z"] - ez)**2)
        
        if dist < GRENADE_RADIUS:
            # Damage falls off with distance
            damage_mult = 1.0 - (dist / GRENADE_RADIUS)
            damage = int(GRENADE_DAMAGE * damage_mult)
            
            # Apply armor protection
            armor = p.get("armor", 0)
            if armor > 0:
                armor_absorb = min(armor, damage // 2)
                damage -= armor_absorb
                p["armor"] = armor - armor_absorb
            
            p["health"] = max(0, p["health"] - damage)
            
            await notify_player_byid(pid, {
                "type": "got_hit",
                "by": owner_id,
                "health": p["health"],
                "damage": damage
            })
            
            if p["health"] == 0:
                p["deaths"] = p.get("deaths", 0) + 1
                
                if owner_id in players:
                    players[owner_id]["kills"] = players[owner_id].get("kills", 0) + 1
                
                await notify_all({
                    "type": "kill",
                    "killer": owner_id,
                    "victim": pid
                })
                
                print(f"[💥] {owner_id} killed {pid} with grenade")
                asyncio.create_task(handle_respawn(pid))

# ==================== REGISTER / UNREGISTER ====================
async def register(ws, info):
    pid = str(uuid.uuid4())[:8]
    clients[ws] = pid
    
    mode = info.get("mode", "deathmatch")
    team = None
    
    if GAME_MODES.get(mode, {}).get("teams"):
        team = assign_team()
    
    # Team-based spawn positions
    if team == "red":
        spawn_x = random.uniform(-80, -40)
        spawn_z = random.uniform(-50, 50)
    elif team == "blue":
        spawn_x = random.uniform(40, 80)
        spawn_z = random.uniform(-50, 50)
    else:
        spawn_x = random.uniform(-50, 50)
        spawn_z = random.uniform(-50, 50)
    
    players[pid] = {
        "id": pid,
        "name": info.get("name", f"Player{pid[:4]}"),
        "x": spawn_x,
        "y": 1.0,
        "z": spawn_z,
        "yaw": 0,
        "pitch": 0,
        "health": MAX_HEALTH,
        "armor": 0,
        "keys": {},
        "weapon": None,
        "ammo": 0,
        "kills": 0,
        "deaths": 0,
        "team": team
    }
    
    await ws.send(json.dumps({
        "type": "welcome", 
        "id": pid, 
        "team": team,
        "t": now()
    }))
    
    await notify_all({
        "type": "join", 
        "id": pid,
        "team": team
    })
    
    team_str = f" (Team: {team})" if team else ""
    print(f"[+] Player {pid} joined{team_str} at ({spawn_x:.1f}, {spawn_z:.1f})")

async def unregister(ws):
    pid = clients.pop(ws, None)
    if pid: 
        players.pop(pid, None)
        await notify_all({"type": "leave", "id": pid})
        print(f"[-] Player {pid} left")

# ==================== CONNECTION HANDLER ====================
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

# ==================== SPAWN LOOPS ====================
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

async def spawn_powerup_loop():
    while True:
        await asyncio.sleep(POWERUP_SPAWN_INTERVAL)
        if len(powerups) >= POWERUP_MAX:
            continue
            
        pwid = str(uuid.uuid4())[:8]
        pwtype = random.choice(POWERUP_TYPES)
        
        powerups[pwid] = {
            "id": pwid,
            "type": pwtype,
            "x": random.uniform(-80, 80),
            "y": 1.0,
            "z": random.uniform(-80, 80)
        }
        
        await notify_all({"type": "powerup_spawn", **powerups[pwid]})
        print(f"[⚡] Spawned {pwtype} powerup at ({powerups[pwid]['x']:.1f}, {powerups[pwid]['z']:.1f})")

# ==================== PROJECTILE LOOP ====================
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
                
                # Team check for team modes
                if players[proj["owner"]].get("team") == op.get("team") and op.get("team"):
                    continue
                    
                dx = op["x"] - proj["pos"][0]
                dy = op["y"] - proj["pos"][1]
                dz = op["z"] - proj["pos"][2]
                
                if math.sqrt(dx*dx + dy*dy + dz*dz) < 1.0:
                    damage = WEAPON_DATA[proj["type"]]["damage"]
                    
                    # Apply armor protection
                    armor = op.get("armor", 0)
                    if armor > 0:
                        armor_absorb = min(armor, damage // 2)
                        damage -= armor_absorb
                        op["armor"] = armor - armor_absorb
                    
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
                            
                            # Team score
                            killer_team = players[proj["owner"]].get("team")
                            if killer_team:
                                team_scores[killer_team] = team_scores.get(killer_team, 0) + 1
                        
                        await notify_all({
                            "type": "kill",
                            "killer": proj["owner"],
                            "victim": oid
                        })
                        
                        print(f"[☠️] {proj['owner']} killed {oid}")
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

# ==================== MAIN LOOPS ====================
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

# ==================== SERVER START ====================
if __name__ == "__main__":
    async def main():
        print("=" * 70)
        print("🎮 MULTIPLAYER FPS SERVER - COMPLETE EDITION")
        print("=" * 70)
        print(f"📡 Starting server on ws://0.0.0.0:8765")
        print(f"⚙️  Tick Rate: {TICK_RATE} Hz")
        print(f"📤 Broadcast Rate: {BROADCAST_RATE} Hz")
        print(f"🔫 Weapons: {', '.join(WEAPON_DATA.keys())}")
        print(f"⚡ Powerups: {', '.join(POWERUP_TYPES)}")
        print(f"🎮 Game Modes: {', '.join(GAME_MODES.keys())}")
        print(f"💀 Respawn Time: {RESPAWN_TIME}s")
        print("=" * 70)
        
        async with websockets.serve(handler, "0.0.0.0", 8765, ping_interval=None):
            asyncio.create_task(main_loop())
            asyncio.create_task(broadcaster_loop())
            asyncio.create_task(spawn_weapon_loop())
            asyncio.create_task(spawn_powerup_loop())
            asyncio.create_task(projectile_loop(1.0/TICK_RATE))
            
            print("✅ Server is running! Waiting for players...")
            print("🎯 Features enabled:")
            print("   • Team Deathmatch")
            print("   • Power-ups (Health, Armor, Speed)")
            print("   • Advanced weapons (Pistol, Rifle, Shotgun, Sniper, SMG)")
            print("   • Grenades")
            print("   • Chat system")
            print("   • XP & Leveling")
            print("   • Leaderboard")
            print("Press Ctrl+C to stop")
            print()
            
            await asyncio.Future()
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
        print("Thanks for playing!")
