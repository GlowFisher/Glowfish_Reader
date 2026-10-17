import { readdir, stat } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";

const source = path.resolve(import.meta.dirname, "..", "src");

async function javascriptFiles(directory) {
  const result = [];
  for (const name of await readdir(directory)) {
    const absolute = path.join(directory, name);
    if ((await stat(absolute)).isDirectory()) result.push(...await javascriptFiles(absolute));
    else if (name.endsWith(".js")) result.push(absolute);
  }
  return result.sort();
}

for (const file of await javascriptFiles(source)) {
  const check = spawnSync(process.execPath, ["--check", file], { stdio: "inherit" });
  if (check.status !== 0) process.exit(check.status ?? 1);
}
