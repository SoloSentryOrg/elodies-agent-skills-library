#!/usr/bin/env node
// SPDX-License-Identifier: MIT
/** Bind a prepared artifact-tool workspace to an immutable local runtime receipt. */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";

function fail(message) {
  process.stderr.write(`create_artifact_runtime_receipt: ${message}\n`);
  process.exit(2);
}

async function stableFile(filename, field) {
  let handle;
  try {
    const pathInfo = await fs.lstat(filename);
    if (!pathInfo.isFile() || pathInfo.isSymbolicLink()) throw new Error(`${field} must be a regular non-symlink file`);
    handle = await fs.open(filename, fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0));
    const before = await handle.stat();
    if (!before.isFile() || before.size > 64 * 1024 * 1024) throw new Error(`${field} must be a bounded regular file`);
    const data = await handle.readFile();
    const after = await handle.stat();
    if (pathInfo.dev !== before.dev || pathInfo.ino !== before.ino || before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
      throw new Error(`${field} changed while being read`);
    }
    return data;
  } finally {
    if (handle) await handle.close();
  }
}

function digest(data) { return crypto.createHash("sha256").update(data).digest("hex"); }

async function packageTree(root) {
  const files = [];
  let total = 0;
  async function walk(directory, relative = "") {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.name === "." || entry.name === ".." || entry.name.includes("\0")) throw new Error("artifact-tool package tree contains an unsafe name");
      const childRelative = relative ? `${relative}/${entry.name}` : entry.name;
      const child = path.join(directory, entry.name);
      if (entry.isSymbolicLink() || (!entry.isFile() && !entry.isDirectory())) throw new Error(`artifact-tool package tree contains a symlink or special entry: ${childRelative}`);
      if (entry.isDirectory()) await walk(child, childRelative);
      else {
        const data = await stableFile(child, `artifact-tool package file ${childRelative}`);
        total += data.length;
        if (files.length >= 10000 || total > 512 * 1024 * 1024) throw new Error("artifact-tool package tree exceeds receipt bounds");
        files.push({ path: childRelative, size: data.length, sha256: digest(data) });
      }
    }
  }
  await walk(root);
  return files;
}

async function main() {
  const args = process.argv.slice(2);
  const values = {};
  for (let index = 0; index < args.length; index += 2) {
    if (!new Set(["--workspace", "--trusted-runtime-root", "--output", "--montage-helper", "--python"]).has(args[index]) || !args[index + 1]) fail("usage: --workspace DIR --trusted-runtime-root DIR --output RECEIPT.json [--montage-helper FILE --python VENV_PYTHON]");
    values[args[index].slice(2)] = args[index + 1];
  }
  if (!values.workspace || !values["trusted-runtime-root"] || !values.output) fail("--workspace, --trusted-runtime-root, and --output are required");
  const workspace = await fs.realpath(path.resolve(values.workspace));
  const workspaceInfo = await fs.lstat(workspace);
  if (!workspaceInfo.isDirectory() || workspaceInfo.isSymbolicLink()) fail("workspace must be a real directory");
  const packageFile = path.join(workspace, "package.json");
  const packageData = await stableFile(packageFile, "workspace package.json");
  const requireFromWorkspace = createRequire(packageFile);
  let entrypoint;
  try { entrypoint = await fs.realpath(requireFromWorkspace.resolve("@oai/artifact-tool")); }
  catch { fail("workspace does not resolve @oai/artifact-tool"); }
  const packageLink = path.join(workspace, "node_modules", "@oai", "artifact-tool");
  let linkedPackageRoot;
  try { linkedPackageRoot = await fs.realpath(packageLink); }
  catch { fail("workspace must explicitly provide node_modules/@oai/artifact-tool"); }
  let cursor = path.dirname(entrypoint);
  let packageRoot = null;
  let metadata = null;
  let artifactPackageData = null;
  for (let depth = 0; depth < 10; depth += 1) {
    const candidate = path.join(cursor, "package.json");
    try {
      const bytes = await stableFile(candidate, "artifact-tool package.json");
      const parsed = JSON.parse(bytes.toString("utf8"));
      if (parsed.name === "@oai/artifact-tool") { packageRoot = cursor; metadata = parsed; artifactPackageData = bytes; break; }
    } catch (error) { if (error.code !== "ENOENT" && !(error instanceof SyntaxError)) throw error; }
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
  if (!packageRoot || !metadata || !/^\d+\.\d+\.\d+/.test(metadata.version || "")) fail("artifact-tool package identity is invalid");
  const trustedRuntimeRoot = await fs.realpath(path.resolve(values["trusted-runtime-root"]));
  if (path.relative(trustedRuntimeRoot, packageRoot).startsWith("..") || packageRoot === trustedRuntimeRoot) {
    fail("artifact-tool package must remain beneath the explicitly trusted runtime root");
  }
  if (packageRoot !== linkedPackageRoot || path.relative(packageRoot, entrypoint).startsWith("..")) {
    fail("resolved artifact-tool must originate from the workspace package link");
  }
  const entrypointData = await stableFile(entrypoint, "artifact-tool entrypoint");
  const payload = {
    schema_version: 1,
    package: "@oai/artifact-tool",
    version: metadata.version,
    trusted_runtime_root: trustedRuntimeRoot,
    workspace,
    workspace_package_sha256: digest(packageData),
    package_root: packageRoot,
    package_link: packageLink,
    package_json_sha256: digest(artifactPackageData),
    entrypoint,
    entrypoint_sha256: digest(entrypointData),
    package_tree: await packageTree(packageRoot),
  };
  if (values["montage-helper"]) {
    if (!values.python) fail("--python is required with --montage-helper");
    const helper = await fs.realpath(path.resolve(values["montage-helper"]));
    payload.montage_helper = { path: helper, sha256: digest(await stableFile(helper, "montage helper")) };
    const requestedLauncher = path.resolve(values.python);
    const launcherParent = await fs.realpath(path.dirname(requestedLauncher));
    const launcher = path.join(launcherParent, path.basename(requestedLauncher));
    const launcherInfo = await fs.lstat(launcher);
    if (!launcherInfo.isFile() && !launcherInfo.isSymbolicLink()) fail("Python launcher must be a regular file or venv symlink");
    const target = await fs.realpath(launcher);
    const targetData = await stableFile(target, "Python launcher target");
    const pyvenvPath = path.join(path.dirname(path.dirname(launcher)), "pyvenv.cfg");
    const pyvenvData = await stableFile(pyvenvPath, "Python virtual-environment configuration");
    payload.python_runtime = {
      launcher,
      launcher_kind: launcherInfo.isSymbolicLink() ? "symlink" : "file",
      launcher_target: launcherInfo.isSymbolicLink() ? await fs.readlink(launcher) : null,
      target,
      target_sha256: digest(targetData),
      pyvenv_cfg: { path: pyvenvPath, sha256: digest(pyvenvData) },
    };
  }
  const output = path.resolve(values.output);
  const parent = await fs.realpath(path.dirname(output));
  if (path.join(parent, path.basename(output)) !== output) fail("output must use a canonical existing parent");
  await fs.writeFile(output, `${JSON.stringify(payload, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  process.stdout.write(`${JSON.stringify({ status: "created", output, version: metadata.version })}\n`);
}

main().catch((error) => fail(error.message));
