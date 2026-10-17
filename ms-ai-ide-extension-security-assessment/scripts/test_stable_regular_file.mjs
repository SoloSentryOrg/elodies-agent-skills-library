// SPDX-License-Identifier: MIT
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { readStableRegularFile } from "./stable_regular_file.mjs";

async function fixture(run) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "stable-file-"));
  try { await run(directory); }
  finally { await fs.rm(directory, { recursive: true, force: true }); }
}

test("empty and exact-bound files preserve bytes and descriptor identity", () => fixture(async (dir) => {
  const filename = path.join(dir, "input");
  for (const bytes of [Buffer.alloc(0), Buffer.from("exact")]) {
    await fs.writeFile(filename, bytes);
    const result = await readStableRegularFile(filename, "input", bytes.length);
    assert.deepEqual(result.data, bytes);
    assert.equal(result.stat.ino, (await fs.lstat(filename, { bigint: true })).ino);
  }
}));

test("oversized files and directories reject without returning bytes", () => fixture(async (dir) => {
  const filename = path.join(dir, "input");
  await fs.writeFile(filename, "large");
  await assert.rejects(readStableRegularFile(filename, "input", 4));
  await assert.rejects(readStableRegularFile(dir, "directory"));
}));

test("direct symlinks reject", (t) => fixture(async (dir) => {
  const filename = path.join(dir, "input"), link = path.join(dir, "link");
  await fs.writeFile(filename, "trusted");
  try { await fs.symlink(filename, link, "file"); }
  catch (error) {
    if (process.platform === "win32" && error.code === "EPERM") { t.skip("host lacks symlink privilege"); return; }
    throw error;
  }
  await assert.rejects(readStableRegularFile(link, "link"));
}));

test("FIFO opens reject promptly without a writer", { skip: process.platform === "win32" }, () => fixture(async (dir) => {
  const fifo = path.join(dir, "fifo");
  execFileSync("mkfifo", [fifo]);
  const module = new URL("./stable_regular_file.mjs", import.meta.url).href;
  const script = `import {readStableRegularFile} from ${JSON.stringify(module)}; try { await readStableRegularFile(process.argv[1], 'fifo'); process.exitCode=1; } catch { process.exitCode=0; }`;
  const result = spawnSync(process.execPath, ["--input-type=module", "-e", script, fifo], { timeout: 2000 });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0);
}));

test("path replacement after open rejects and closes its descriptor", () => fixture(async (dir) => {
  const filename = path.join(dir, "input");
  await fs.writeFile(filename, "trusted");
  const open = fs.open; let closed = false;
  fs.open = async (...args) => {
    const handle = await open(...args), close = handle.close.bind(handle);
    handle.close = async () => { closed = true; return close(); };
    await fs.rename(filename, path.join(dir, "original"));
    await fs.writeFile(filename, "changed");
    return handle;
  };
  try { await assert.rejects(readStableRegularFile(filename, "input")); assert.equal(closed, true); }
  finally { fs.open = open; }
}));

for (const mode of ["append", "truncate", "same-size rewrite"]) {
  test(`${mode} during a descriptor read rejects and closes`, () => fixture(async (dir) => {
    const filename = path.join(dir, "input");
    await fs.writeFile(filename, "trusted");
    const open = fs.open; let closed = false;
    fs.open = async (...args) => {
      const handle = await open(...args), read = handle.read.bind(handle), close = handle.close.bind(handle);
      let changed = false;
      handle.close = async () => { closed = true; return close(); };
      handle.read = async (...readArgs) => {
        const result = await read(...readArgs);
        if (!changed) {
          changed = true;
          if (mode === "append") await fs.appendFile(filename, "extra");
          else if (mode === "truncate") await fs.truncate(filename, 0);
          else { await fs.writeFile(filename, "changed"); await fs.utimes(filename, 1, 1); }
        }
        return result;
      };
      return handle;
    };
    try { await assert.rejects(readStableRegularFile(filename, "input")); assert.equal(closed, true); }
    finally { fs.open = open; }
  }));
}
