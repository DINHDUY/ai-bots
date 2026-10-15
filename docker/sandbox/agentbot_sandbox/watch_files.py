#!/usr/bin/env python3
"""Coalesced invalidations with inotify and bounded full rescans."""

import ctypes
import json
import os
from pathlib import Path
import select
import time
import uuid
import struct

libc = ctypes.CDLL(None, use_errno=True)
descriptor = libc.inotify_init1(os.O_NONBLOCK)
epoch, sequence, previous = uuid.uuid4().hex, 0, {}
state = Path("/tmp/agentbot-file-changes.json")
queue_overflow = False


def scan():
    entries, overflow, directories = {}, False, []
    for root, dirs, files in os.walk("/workspace", followlinks=False):
        dirs[:] = [
            name for name in dirs if not os.path.islink(os.path.join(root, name))
        ]
        directories.append(root)
        for name in dirs + files:
            path = os.path.join(root, name)
            try:
                info = os.lstat(path)
                entries[path] = (info.st_mtime_ns, info.st_size, info.st_mode)
            except FileNotFoundError:
                continue
            if len(entries) >= 10000:
                overflow = True
                break
        if overflow:
            break
    if descriptor >= 0:
        for directory in directories[:1000]:
            if libc.inotify_add_watch(descriptor, directory.encode(), 0x00000FCF) < 0:
                overflow = True
    return entries, overflow


while True:
    current, overflow = scan()
    overflow = overflow or queue_overflow
    queue_overflow = False
    if current != previous or sequence == 0 or overflow:
        changes = [
            {
                "path": p,
                "kind": "deleted"
                if p not in current
                else "created"
                if p not in previous
                else "modified",
            }
            for p in (current.keys() | previous.keys())
            if current.get(p) != previous.get(p)
        ]
        sequence += 1
        temporary = state.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "epoch": epoch,
                    "sequence": sequence,
                    "rescan": True,
                    "overflow": overflow or len(changes) > 200,
                    "changes": changes[:200],
                }
            )
        )
        temporary.replace(state)
        previous = current
    if descriptor >= 0:
        ready, _, _ = select.select([descriptor], [], [], 2)
        if ready:
            try:
                data = os.read(descriptor, 65536)
                offset = 0
                while offset + 16 <= len(data):
                    _, mask, _, length = struct.unpack_from("iIII", data, offset)
                    queue_overflow |= bool(mask & 0x00004000)
                    offset += 16 + length
            except BlockingIOError:
                pass
    else:
        time.sleep(2)
    time.sleep(0.25)
