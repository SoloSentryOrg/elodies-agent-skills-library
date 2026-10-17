// SPDX-License-Identifier: MIT
import fs from "node:fs/promises";
import { constants } from "node:fs";

const sameIdentity = (a, b) => a.dev === b.dev && a.ino === b.ino;
const sameSnapshot = (a, b) => sameIdentity(a, b) && a.size === b.size
  && a.mtimeNs === b.mtimeNs && a.ctimeNs === b.ctimeNs;

/** Read only the verified descriptor; never consume bytes from a special file. */
export async function readStableRegularFile(filename, field, maximum = 512 * 1024 * 1024) {
  if (!Number.isSafeInteger(maximum) || maximum < 0) throw new Error("invalid file read bound");
  // Windows has no POSIX FIFO open semantics or these Node flags. Validate the
  // opened handle and leaf identity before reading on every supported host.
  let flags = constants.O_RDONLY;
  if (process.platform !== "win32") {
    if (constants.O_NOFOLLOW === undefined || constants.O_NONBLOCK === undefined) {
      throw new Error(`${field} requires secure filesystem open flags`);
    }
    flags |= constants.O_NOFOLLOW | constants.O_NONBLOCK;
  }
  let handle;
  try {
    handle = await fs.open(filename, flags);
    const before = await handle.stat({ bigint: true });
    if (!before.isFile() || before.size > BigInt(maximum)) {
      throw new Error(`${field} must be a bounded regular file`);
    }
    const pathBefore = await fs.lstat(filename, { bigint: true });
    if (!pathBefore.isFile() || pathBefore.isSymbolicLink() || !sameSnapshot(before, pathBefore)) {
      throw new Error(`${field} must be a stable regular non-symlink file`);
    }
    const data = Buffer.alloc(Number(before.size));
    let offset = 0;
    while (offset < data.length) {
      const { bytesRead } = await handle.read(data, offset, Math.min(64 * 1024, data.length - offset), offset);
      if (bytesRead === 0) throw new Error(`${field} changed while being read`);
      offset += bytesRead;
    }
    const probe = Buffer.alloc(1);
    const { bytesRead: extra } = await handle.read(probe, 0, 1, offset);
    const after = await handle.stat({ bigint: true });
    const pathAfter = await fs.lstat(filename, { bigint: true });
    if (extra !== 0 || !sameSnapshot(before, after) || !pathAfter.isFile()
      || pathAfter.isSymbolicLink() || !sameSnapshot(after, pathAfter)) {
      throw new Error(`${field} changed while being read`);
    }
    return { data, stat: after };
  } finally {
    if (handle) await handle.close();
  }
}
