// Utils generici
export let scene, camera, renderer;

export function initScene() {
  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x333333, 50, 200);

  camera = new THREE.PerspectiveCamera(90, innerWidth/innerHeight, 0.1, 1000);
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  document.body.appendChild(renderer.domElement);

  window.addEventListener('resize', () => {
    camera.aspect = innerWidth/innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  // Luci
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
  dirLight.position.set(10, 20, 10);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 2048;
  dirLight.shadow.mapSize.height = 2048;
  scene.add(dirLight);

  const ambLight = new THREE.AmbientLight(0x404040, 0.3);
  scene.add(ambLight);

  // Pavimento
  const floorGeometry = new THREE.PlaneGeometry(200, 200, 20, 20);
  const floorMaterial = new THREE.MeshStandardMaterial({ color:0x444444, roughness:0.8, metalness:0.1 });
  const floor = new THREE.Mesh(floorGeometry, floorMaterial);
  floor.rotation.x = -Math.PI/2;
  floor.position.y = 0;
  floor.receiveShadow = true;
  scene.add(floor);
}

// Lerp
export function lerp(a,b,t) { return a + (b-a)*t; }
