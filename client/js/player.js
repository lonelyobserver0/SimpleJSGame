import * as THREE from 'three';
import { scene } from './utils.js';

export class Player {
  constructor(id, x=0, y=1, z=0){
    this.id = id;
    this.x = x; this.y = y; this.z = z;
    this.yaw = 0; this.pitch = 0;
    this.health = 100;

    // Mesh
    const geometry = new THREE.CapsuleGeometry(0.3,1.0,4,8);
    const material = new THREE.MeshStandardMaterial({ color:0x00ff00 });
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.castShadow = true;
    this.mesh.position.set(this.x,this.y,this.z);
    scene.add(this.mesh);
  }

  update(dt){
    this.mesh.position.set(this.x,this.y,this.z);
    this.mesh.rotation.y = this.yaw;
  }

  applyDamage(amount){
    this.health -= amount;
    this.health = Math.max(this.health,0);
  }

  remove(){
    scene.remove(this.mesh);
  }
}
