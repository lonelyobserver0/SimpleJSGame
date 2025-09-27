import * as THREE from 'three';
import { scene } from './utils.js';

export const targets = {};

export class Target {
  constructor(id, x, y, z){
    this.id = id;
    this.x = x; this.y = y; this.z = z;
    this.health = 100;

    const geometry = new THREE.BoxGeometry(1,1,1);
    const material = new THREE.MeshStandardMaterial({ color:0xff0000 });
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.position.set(x,y,z);
    this.mesh.castShadow = true;
    scene.add(this.mesh);

    targets[id] = this;
  }

  applyDamage(amount){
    this.health -= amount;
    if(this.health<=0) this.destroy();
  }

  destroy(){
    scene.remove(this.mesh);
    delete targets[this.id];
  }

  update(dt){
    // Possibili animazioni dei target
    this.mesh.rotation.y += dt;
  }
}
