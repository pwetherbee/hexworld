// Copies the wooden UI button sounds (CelerisLab "Complete UI SFX", a purchased Asset Store pack)
// into frontend/public/sfx. They're licensed assets, so they're gitignored rather than committed;
// the app runs silently without them.
//
//   node scripts/import-sfx.mjs [path/to/basic_interactions_and_navigation]
import { copyFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(
  process.argv[2] ??
    process.env.HEXWORLD_SFX_SRC ??
    "C:/Users/patri/Canals/Assets/CelerisLab/CompleteUISFX/basic_interactions_and_navigation",
  "buttons",
  "wooden_button",
);
const out = join(root, "frontend", "public", "sfx");

if (!existsSync(src)) {
  console.error(`sound folder not found: ${src}`);
  process.exit(1);
}
mkdirSync(out, { recursive: true });
const files = readdirSync(src).filter((f) => f.endsWith(".wav"));
for (const f of files) copyFileSync(join(src, f), join(out, f));
console.log(`copied ${files.length} sounds -> ${out}`);
