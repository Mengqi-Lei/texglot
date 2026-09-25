import { build } from "esbuild";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { zipSync } from "fflate";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const scaffold = join(root, ".scaffold");
const addon = join(root, "addon");
const packageDir = join(scaffold, "package");
const dist = join(packageDir, "dist");
const packageJson = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
const version = packageJson.version;
await rm(scaffold, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await writeFile(join(packageDir, "manifest.json"), await readFile(join(addon, "manifest.json")));
await writeFile(join(packageDir, "bootstrap.js"), await readFile(join(addon, "bootstrap.js")));
await mkdir(join(packageDir, "icons"), { recursive: true });
// Share the same brand asset used by the web UI and native desktop icon builder.
await writeFile(join(packageDir, "icons/texglot.png"), await readFile(join(root, "../../frontend/src/assets/texglot-logo.png")));
await build({
  entryPoints: [join(root, "src/addon.ts")],
  outfile: join(dist, "addon.js"),
  bundle: true,
  format: "iife",
  globalName: "TeXGlotZotero",
  platform: "browser",
  target: "es2022",
  sourcemap: false,
  legalComments: "none",
});
await mkdir(scaffold, { recursive: true });
const archive = join(scaffold, `texglot-zotero-${version}.xpi`);
const entries = {};
for (const relative of ["manifest.json", "bootstrap.js", "dist/addon.js", "icons/texglot.png"]) {
  entries[relative] = await readFile(join(packageDir, relative));
}
await writeFile(archive, zipSync(entries, { level: 6 }));
console.log(`Built ${archive}`);
