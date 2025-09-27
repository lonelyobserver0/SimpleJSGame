import { camera, renderer } from './utils.js';
import { ws } from './network.js';
import { spawnTracer, createMuzzleFlash } from './projectiles.js';
import { weapons } from './weapons.js';

export const localPlayer = {
  x:0, y:1.0, z:0, yaw:0, pitch:0,
  keys:{}, velocity:{x:0,z:0}, weapon:null, ammo:0,
  update(dt) {
    let dx=0,dz=0;
    const yaw=this.yaw;
    const forward={x:Math.sin(yaw),z:Math.cos(yaw)};
    const right={x:Math.sin(yaw+Math.PI/2),z:Math.cos(yaw+Math.PI/2)};
    if(this.keys.forward) { dx+=forward.x; dz+=forward.z; }
    if(this.keys.backward){ dx-=forward.x; dz-=forward.z; }
    if(this.keys.left){ dx-=right.x; dz-=right.z; }
    if(this.keys.right){ dx+=right.x; dz+=right.z; }

    let baseSpeed=5.0;
    if(this.keys.run) baseSpeed*=1.8;
    if(this.keys.crouch) baseSpeed*=0.5;

    const L=Math.hypot(dx,dz);
    if(L>0){ dx=dx/L*baseSpeed; dz=dz/L*baseSpeed; }

    const accel=15.0, decel=12.0;
    this.velocity.x=THREE.MathUtils.lerp(this.velocity.x, dx, dt*(L>0?accel:decel));
    this.velocity.z=THREE.MathUtils.lerp(this.velocity.z, dz, dt*(L>0?accel:decel));
    this.x+=this.velocity.x*dt; this.z+=this.velocity.z*dt;

    this.y=THREE.MathUtils.lerp(this.y, this.keys.crouch?0.7:1.0, dt*8);

    // Camera
    camera.position.set(this.x,this.y+0.6,this.z);
    camera.rotation.set(this.pitch,this.yaw,0,'YXZ');
  },
  pickupWeapon(name, ammo){
    this.weapon=name; this.ammo=ammo;
    document.getElementById('hud_weapon').innerText=`Arma: ${name.toUpperCase()}`;
    document.getElementById('hud_ammo').innerText=`Munizioni: ${ammo}`;
  }
};

let isLocked=false;
const sensitivity=0.002;

export function setupControls(){
  renderer.domElement.addEventListener('click',()=>renderer.domElement.requestPointerLock());
  document.addEventListener('pointerlockchange',()=>{
    isLocked=(document.pointerLockElement===renderer.domElement);
    document.getElementById('crosshair').style.display=isLocked?'block':'none';
  });
  document.addEventListener('mousemove', e=>{
    if(!isLocked) return;
    localPlayer.yaw-=e.movementX*sensitivity;
    localPlayer.pitch-=e.movementY*sensitivity;
    localPlayer.pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,localPlayer.pitch));
  });

  const keyMap={'KeyW':'forward','KeyA':'left','KeyS':'backward','KeyD':'right','ShiftLeft':'run','ControlLeft':'crouch','KeyE':'interact'};
  window.addEventListener('keydown', e=>{
    const a=keyMap[e.code]; if(a){ localPlayer.keys[a]=true; e.preventDefault(); }
  });
  window.addEventListener('keyup', e=>{
    const a=keyMap[e.code]; if(a){ localPlayer.keys[a]=false; e.preventDefault(); }
  });

  renderer.domElement.addEventListener('mousedown', e=>{
    if(e.button!==0||!isLocked) return;
    const dir = {x: Math.sin(localPlayer.yaw), y: 0, z: Math.cos(localPlayer.yaw)};
    if(ws && ws.readyState===WebSocket.OPEN){
      ws.send(JSON.stringify({ type:"shoot", dir }));
    }
    createMuzzleFlash();
    spawnTracer(localPlayer.x, localPlayer.y+0.6, localPlayer.z, dir);
  });

  window.addEventListener('keydown', e=>{
    if(e.code==='KeyE' && isLocked){
      for(const wid in weapons){
        const w=weapons[wid];
        const dist=Math.hypot(localPlayer.x-w.x, localPlayer.z-w.z);
        if(dist<2.0 && ws && ws.readyState===WebSocket.OPEN){
          ws.send(JSON.stringify({type:"pickup",id:wid}));
          break;
        }
      }
    }
  });
}
