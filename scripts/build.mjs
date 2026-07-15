import { createHash } from "node:crypto";
import { cp, mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = path.resolve(import.meta.dirname, "..");
const source = path.join(root, "src");
const outFlag = process.argv.indexOf("--out");
const output = outFlag >= 0 ? path.resolve(process.argv[outFlag + 1]) : path.join(root, "dist");

async function filesUnder(directory, prefix = "") {
  const names = (await readdir(directory)).sort();
  const result = [];
  for (const name of names) {
    const absolute = path.join(directory, name);
    const relative = path.posix.join(prefix, name);
    if ((await stat(absolute)).isDirectory()) result.push(...await filesUnder(absolute, relative));
    else result.push(relative);
  }
  return result;
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(source, output, { recursive: true });

const entries = [];
for (const relative of await filesUnder(output)) {
  const data = await import("node:fs/promises").then(({ readFile }) => readFile(path.join(output, relative)));
  entries.push({ path: relative, bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") });
}
const manifest = { schema_version: 1, component: "glowfish-reader-ui", version: "1.0.0", files: entries };
await writeFile(path.join(output, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");
console.log(`built ${entries.length} UI files at ${output}`);
