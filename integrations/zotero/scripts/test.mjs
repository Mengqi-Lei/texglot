import { build } from "esbuild";
import { mkdir, rm } from "node:fs/promises";
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, ".scaffold", "tests");
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
const files = ["arxiv.test.ts", "source-resolution.test.ts", "bridge.test.ts", "attachments.test.ts", "zotero-runtime.test.ts", "split-reader.test.ts", "status-column.test.ts"];
for (const file of files) {
  await build({ entryPoints: [join(root, "tests", file)], outfile: join(out, file.replace(/\.ts$/, ".mjs")), bundle: true, format: "esm", platform: "node", target: "node20", sourcemap: false });
}
await new Promise((resolvePromise, reject) => {
  const proc = spawn(process.execPath, ["--test", ...files.map((file) => join(out, file.replace(/\.ts$/, ".mjs")))], { stdio: "inherit" });
  proc.on("error", reject);
  proc.on("exit", (code) => code === 0 ? resolvePromise() : reject(new Error(`tests exited with ${code}`)));
});
