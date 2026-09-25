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

/** The texture for `id`, or null while it loads. Never returns a previous id's texture: callers
 * derive geometry from it (canvas size), and a stale value would be cached under the new id. */
export function usePixelTexture(id: string | null | undefined): THREE.Texture | null {
  const [state, setState] = useState<{ id: string; tex: THREE.Texture } | null>(() => {
    const hit = id ? cache.get(id) : undefined;
    return id && hit ? { id, tex: hit } : null;
  });
  useEffect(() => {
    if (!id) return;
    let alive = true;
    const hit = cache.get(id);
    if (hit) setState({ id, tex: hit });
    else load(id).then((t) => alive && setState({ id, tex: t })).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  if (!id) return null;
  if (state?.id === id) return state.tex;
  return cache.get(id) ?? null;
}
