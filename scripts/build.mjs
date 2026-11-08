#!/usr/bin/env node
// Copies the shared web game (web/) into both extensions. No dependencies.
//   node scripts/build.mjs          -> vscode/media, browser/dist/chrome, browser/dist/firefox
//   node scripts/build.mjs --zip    -> also browser/dist/my-data-center-{chrome,firefox}.zip
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const GAME_FILES = ["index.html", "dc.css", "core.js", "ui.js"];

for (const f of GAME_FILES) {
  if (!existsSync(join(root, "web", f))) {
    console.error(`missing web/${f}: the web game has to exist before the extensions can be built`);
    process.exit(1);
  }
}

// VS Code: the extension reads the game from media/
const media = join(root, "vscode", "media");
rmSync(media, { recursive: true, force: true });
mkdirSync(media, { recursive: true });
for (const f of GAME_FILES) cpSync(join(root, "web", f), join(media, f));
console.log("vscode/media            <- web/");

// Browser: one folder per browser. host.js has to load before the game's own scripts.
const dist = join(root, "browser", "dist");
rmSync(dist, { recursive: true, force: true });
for (const target of ["chrome", "firefox"]) {
  const out = join(dist, target);
  const app = join(out, "app");
  mkdirSync(app, { recursive: true });
  for (const f of GAME_FILES.filter((f) => f !== "index.html")) cpSync(join(root, "web", f), join(app, f));
  cpSync(join(root, "browser", "host.js"), join(app, "host.js"));
  cpSync(join(root, "browser", "background.js"), join(out, "background.js"));
  cpSync(join(root, "browser", "icons"), join(out, "icons"), { recursive: true });
  cpSync(join(root, "browser", `manifest.${target}.json`), join(out, "manifest.json"));

  let html = readFileSync(join(root, "web", "index.html"), "utf8");
  const first = html.search(/<script[\s>]/i);
  const tag = '<script src="host.js"></script>\n';
  html = first === -1 ? html + tag : html.slice(0, first) + tag + html.slice(first);
  writeFileSync(join(app, "index.html"), html);
  console.log(`browser/dist/${target.padEnd(8)}  <- web/ + browser/`);
}

if (process.argv.includes("--zip")) {
  for (const target of ["chrome", "firefox"]) {
    const zip = join(dist, `my-data-center-${target}.zip`);
    execFileSync("zip", ["-qr", zip, "."], { cwd: join(dist, target) });
    console.log(`wrote ${zip.replace(root + "/", "")}`);
  }
}
