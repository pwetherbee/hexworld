import { useEffect, useState } from "react";
import * as THREE from "three";
import { assetUrl } from "../api/client";

const cache = new Map<string, THREE.Texture>();
const pending = new Map<string, Promise<THREE.Texture>>();
const loader = new THREE.TextureLoader();

function load(id: string): Promise<THREE.Texture> {
  const hit = cache.get(id);
  if (hit) return Promise.resolve(hit);
  let p = pending.get(id);
  if (!p) {
    p = loader.loadAsync(assetUrl(id)).then((tex) => {
      // Crisp pixel art: no filtering, no mipmaps.
      tex.magFilter = THREE.NearestFilter;
      tex.minFilter = THREE.NearestFilter;
      tex.generateMipmaps = false;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 1;
      cache.set(id, tex);
      pending.delete(id);
      return tex;
    });
    pending.set(id, p);
  }
  return p;
}

export function usePixelTexture(id: string | null | undefined): THREE.Texture | null {
  const [tex, setTex] = useState<THREE.Texture | null>(() => (id ? cache.get(id) ?? null : null));
  useEffect(() => {
    if (!id) {
      setTex(null);
      return;
    }
    let alive = true;
    const hit = cache.get(id);
    if (hit) setTex(hit);
    else load(id).then((t) => alive && setTex(t)).catch(() => alive && setTex(null));
    return () => {
      alive = false;
    };
  }, [id]);
  return tex;
}
