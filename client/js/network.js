import { Player } from './player.js';
import { weapons, Weapon } from './weapons.js';

export let ws = null;
export let myId = null;
export const players = {};

export function connect(SERVER, statusEl, pingEl, btnConnect, local){
  if(ws && ws.readyState === WebSocket.OPEN) ws.close();

  ws = new WebSocket(SERVER);

  ws.onopen = () => {
    statusEl.innerText = "connected";
    btnConnect.innerText = "Disconnetti";
    ws.send(JSON.stringify({ name: "Player" }));

    // Ping test
    setInterval(() => {
      if(ws && ws.readyState === WebSocket.OPEN){
        const pingStart = performance.now();
        ws.send(JSON.stringify({ type:"ping", timestamp:pingStart }));
      }
    },2000);
  };

  ws.onmessage = ev => handleMessage(JSON.parse(ev.data), local, statusEl, pingEl);
  ws.onclose = () => { statusEl.innerText = "disconnected"; btnConnect.innerText = "Connetti"; };
  ws.onerror = e => { statusEl.innerText = "error"; console.error(e); };
}

function handleMessage(msg, local, statusEl, pingEl){
  if(msg.type === "welcome"){
    myId = msg.id;
    console.log("ID:", myId);
    if(!players[myId]) players[myId] = new Player(myId);
  }
  else if(msg.type === "ping"){
    const currentPing = Math.round(performance.now() - msg.timestamp);
    pingEl.innerText = currentPing;
  }
  else if(msg.type === "state"){
    msg.players.forEach(p => {
      if(!players[p.id]) players[p.id] = new Player(p.id);
      Object.assign(players[p.id], p);
    });

    const ids = new Set(msg.players.map(p=>p.id));
    for(const id in players){
      if(!ids.has(id)){
        players[id].remove();
        delete players[id];
      }
    }

    // Gestione armi
    msg.weapons.forEach(w => {
      if(!weapons[w.id]) new Weapon(w.id, w.type, w.x, w.y, w.z);
      else {
        weapons[w.id].mesh.position.set(w.x, w.y, w.z);
      }
    });
  }
  else if(msg.type === "weapon_pickup"){
    if(players[myId]){
      players[myId].weapon = msg.weapon;
      players[myId].ammo = msg.ammo;
    }
  }
}
