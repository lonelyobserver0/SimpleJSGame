import * as THREE from 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.module.min.js';
import { Player, players } from './player.js';
import { weapons } from './weapons.js';
import { spawnTracer, createMuzzleFlash, updateProjectiles } from './projectiles.js';
import { connect, ws } from './network.js';
import { targets } from './targets.js';

// CAMERA & RENDERER
export const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x333333,50,200);

export const camera = new THREE.PerspectiveCamera(90, innerWidth/innerHeight,0.1,1000);
export const renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.setSize(innerWidth,innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(renderer.domElement);

window.addEventListener('resize',()=>{
  camera.aspect = innerWidth/innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth,innerHeight);
});

// LUCI
const dirLight = new THREE.DirectionalLight(0xffffff,1.0);
dirLight.position.set(10,20,10);
dirLight.castShadow = true;
scene.add(dirLight);
scene.add(new THREE.AmbientLight(0x404040,0.3));

// PAVIMENTO
const floor = new THREE.Mesh(new THREE.PlaneGeometry(200,200,20,20),
  new THREE.MeshStandardMaterial({ color:0x444444, roughness:0.8, metalness:0.1 }));
floor.rotation.x = -Math.PI/2; floor.receiveShadow = true;
scene.add(floor);

// CONTROLLI LOCALI
export const local = { x:0,y:1,z:0,yaw:0,pitch:0,keys:{},velocity:{x:0,z:0} };
let isLocked=false;
const sensitivity=0.002;

renderer.domElement.addEventListener('click',()=>renderer.domElement.requestPointerLock());
document.addEventListener('pointerlockchange',()=>isLocked=(document.pointerLockElement===renderer.domElement));

document.addEventListener('mousemove',e=>{
  if(!isLocked) return;
  local.yaw -= e.movementX*sensitivity;
  local.pitch -= e.movementY*sensitivity;
  local.pitch = Math.max(-Math.PI/2,Math.min(Math.PI/2,local.pitch));
});

const keyActions = {'KeyW':'forward','KeyA':'left','KeyS':'backward','KeyD':'right',
'ShiftLeft':'run','ControlLeft':'crouch','KeyE':'interact'};

window.addEventListener('keydown',e=>{ const a=keyActions[e.code]; if(a){ local.keys[a]=true; e.preventDefault(); }});
window.addEventListener('keyup',e=>{ const a=keyActions[e.code]; if(a){ local.keys[a]=false; e.preventDefault(); }});

renderer.domElement.addEventListener('mousedown',e=>{
  if(e.button!==0||!isLocked) return;
  const dir = { x: Math.sin(local.yaw), y:0, z:Math.cos(local.yaw) };
  if(ws && ws.readyState===WebSocket.OPEN) ws.send(JSON.stringify({ type:"shoot", dir:dir }));
  createMuzzleFlash();
  spawnTracer(local.x, local.y+0.6, local.z, dir);
});

// ANIMATE LOOP
let lastFrame = performance.now();
export function animate(){
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min((now-lastFrame)/1000,1/30);
  lastFrame = now;

  // MOVIMENTO LOCALE
  simulateLocal(dt);

  camera.position.set(local.x, local.y+0.6, local.z);
  camera.rotation.set(local.pitch, local.yaw,0,'YXZ');

  // UPDATE PLAYERS
  for(const id in players) players[id].update(dt);

  updateProjectiles(dt);

  renderer.render(scene,camera);
}

function simulateLocal(dt){
  let dx=0,dz=0;
  const yaw=local.yaw;
  const forward={x:Math.sin(yaw),z:Math.cos(yaw)};
  const right={x:Math.sin(yaw+Math.PI/2),z:Math.cos(yaw+Math.PI/2)};

  if(local.keys.forward){ dx+=forward.x; dz+=forward.z; }
  if(local.keys.backward){ dx-=forward.x; dz-=forward.z; }
  if(local.keys.left){ dx-=right.x; dz-=right.z; }
  if(local.keys.right){ dx+=right.x; dz+=right.z; }

  let baseSpeed=5; if(local.keys.run) baseSpeed*=1.8; if(local.keys.crouch) baseSpeed*=0.5;
  const L=Math.hypot(dx,dz);
  if(L>0){ dx=(dx/L)*baseSpeed; dz=(dz/L)*baseSpeed; }

  const accel=15,decel=12;
  local.velocity.x = THREE.MathUtils.lerp(local.velocity.x,dx,dt*(L>0?accel:decel));
  local.velocity.z = THREE.MathUtils.lerp(local.velocity.z,dz,dt*(L>0?accel:decel));

  local.x+=local.velocity.x*dt;
  local.z+=local.velocity.z*dt;
  const targetY = local.keys.crouch?0.7:1.0;
  local.y = THREE.MathUtils.lerp(local.y,targetY,dt*8);
}

// START
animate();
