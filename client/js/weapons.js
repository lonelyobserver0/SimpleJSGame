import * as THREE from 'three';
import { scene } from './utils.js';

export const weapons = {};

export class Weapon {
  constructor(id, name, x, y, z, ammo=30){
    this.id=id; this.name=name; this.x=x; this.y=y; this.z=z; this.ammo=ammo;

    const geometry = new THREE.BoxGeometry(0.3,0.2,0.7);
    const material = new THREE.MeshStandardMaterial({ color:0xffaa00 });
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.position.set(x,y,z);
    this.mesh.castShadow = true;
    scene.add(this.mesh);

    weapons[id] = this;
  }

  remove(){
    scene.remove(this.mesh);
    delete weapons[this.id];
  }
}
