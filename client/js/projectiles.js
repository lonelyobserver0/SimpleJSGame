import * as THREE from 'three';
import { scene } from './utils.js';

const tracers = [];

export function spawnTracer(x,y,z,dir){
  const geometry = new THREE.CylinderGeometry(0.02,0.02,0.5,6);
  const material = new THREE.MeshBasicMaterial({ color:0xffff00 });
  const tracer = new THREE.Mesh(geometry, material);
  tracer.position.set(x+dir.x*0.5, y+0.2, z+dir.z*0.5);
  tracer.rotation.x = Math.PI/2;
  scene.add(tracer);
  tracers.push({mesh:tracer, dir:dir, life:0.2});
}

export function createMuzzleFlash(){
  const geometry = new THREE.SphereGeometry(0.1,6,6);
  const material = new THREE.MeshBasicMaterial({ color:0xffaa00 });
  const flash = new THREE.Mesh(geometry, material);
  scene.add(flash);
  setTimeout(()=>scene.remove(flash),50);
}

export function updateProjectiles(dt){
  for(let i=tracers.length-1;i>=0;i--){
    const t = tracers[i];
    t.mesh.position.x += t.dir.x*dt*20;
    t.mesh.position.y += t.dir.y*dt*20;
    t.mesh.position.z += t.dir.z*dt*20;
    t.life -= dt;
    if(t.life<=0){
      scene.remove(t.mesh);
      tracers.splice(i,1);
    }
  }
}
