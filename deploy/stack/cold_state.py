#!/usr/bin/env python3
"""Conservative cold clones of three explicit stores; never starts or repairs apps.

The storage seam accepts a zero-argument Docker observation callable for isolated
filesystem tests. The operator CLI always uses live local Docker inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import tarfile


class Refused(RuntimeError):
    """Evidence is unsafe, unsupported or has changed; originals remain owned."""


def _require(condition, message):
    if not condition:
        raise Refused(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _read_json(raw):
    return json.loads(raw, object_pairs_hook=_unique)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and path == Path(os.path.abspath(path)), "absolute normalized paths required")
    _require(path.resolve(strict=True) == path, "symlinked or missing path")
    return path


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _stat_fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns,
            info.st_size, info.st_mode, info.st_uid, info.st_gid, info.st_nlink]


def _entry(info, kind, digest=None):
    result = {"kind": kind, "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid,
              "gid": info.st_gid, "mtime_ns": info.st_mtime_ns,
              "size": info.st_size if kind == "file" else 0}
    if digest is not None:
        result["sha256"] = digest
    return result


def _open_dir(path):
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "absolute directory required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            nested = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nested
        return fd
    except BaseException:
        os.close(fd)
        raise


def _check_attrs(fd):
    # ACLs/xattrs are not represented by this deliberately small format.
    if hasattr(os, "listxattr"):
        _require(not os.listxattr(fd), "extended attributes/ACLs require owner-managed recovery")


def _inventory(root):
    entries, fingerprints = {}, {}
    root_fd = _open_dir(root)
    device = os.fstat(root_fd).st_dev

    def visit(fd, name):
        before = os.fstat(fd)
        _require(before.st_dev == device, "nested filesystem in store")
        _check_attrs(fd)
        entries[name] = _entry(before, "dir")
        fingerprints[name] = _stat_fingerprint(before)
        for child in sorted(os.listdir(fd)):
            _require(child not in (".", "..") and "/" not in child, "unsafe filename")
            relative = f"{name}/{child}" if name else child
            info = os.stat(child, dir_fd=fd, follow_symlinks=False)
            _require(info.st_dev == device, "nested filesystem in store")
            if stat.S_ISDIR(info.st_mode):
                nested = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    _require(_stat_fingerprint(os.fstat(nested)) == _stat_fingerprint(info), "directory changed")
                    visit(nested, relative)
                finally:
                    os.close(nested)
            else:
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "symlink, hardlink or special file")
                item = os.open(child, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    _require(_stat_fingerprint(os.fstat(item)) == _stat_fingerprint(info), "file changed")
                    _check_attrs(item)
                    with os.fdopen(os.dup(item), "rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    _require(_stat_fingerprint(os.fstat(item)) == _stat_fingerprint(info), "file changed while hashing")
                finally:
                    os.close(item)
                entries[relative] = _entry(info, "file", digest)
                fingerprints[relative] = _stat_fingerprint(info)
        _require(_stat_fingerprint(os.fstat(fd)) == _stat_fingerprint(before), "directory changed while reading")
    try:
        visit(root_fd, "")
        _require(_stat_fingerprint(os.stat(root, follow_symlinks=False)) == fingerprints[""], "root changed")
    finally:
        os.close(root_fd)
    return {"entries": entries, "stat_fingerprints": fingerprints}


def _layout(plan):
    _require(set(plan) == {"version", "stores", "processes", "fence", "credential_roots"}, "unknown or missing plan fields")
    _require(all(set(store) == {"source", "container", "destination"} for store in plan["stores"].values()),
             "unknown or missing store fields")
    _require(all(set(process) in ({"id", "image"}, {"id", "image", "exit_code"})
                 for process in plan["processes"].values()), "unknown or missing process fields")
    _require(all(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", role) for role in plan["processes"]), "invalid process role")
    _require(plan.get("version") == 1, "unsupported plan version")
    _require(set(plan["stores"]) == {"server", "bridge", "mongo"}, "exactly server, bridge and mongo stores required")
    roots = {role: _path(store["source"]) for role, store in plan["stores"].items()}
    _require(all(path.is_dir() and path != Path("/") for path in roots.values()), "store root must be a directory")
    fence = _path(plan["fence"])
    _require(fence.is_file(), "independent current fence must be a regular file")
    credentials = [_path(path) for path in plan["credential_roots"]]
    _require(credentials, "explicit external credential roots required")
    protected = [fence, *credentials]
    _require(all(not _overlap(a, b) for i, a in enumerate(roots.values())
                 for b in list(roots.values())[i + 1:]), "overlapping stores")
    _require(all(not _overlap(root, other) for root in roots.values() for other in protected),
             "fence and credential roots must stay outside archives")
    return roots, fence, credentials


def _fence(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe fence file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        _require(_stat_fingerprint(os.fstat(fd)) == _stat_fingerprint(info), "fence changed while hashing")
        _require(_stat_fingerprint(os.stat(path, follow_symlinks=False)) == _stat_fingerprint(info), "fence replaced")
        return {"sha256": digest, "stat_fingerprint": _stat_fingerprint(info)}
    finally:
        os.close(fd)


def _cold(plan, observe, extra_roots=()):
    observed = observe()
    by_id = {item["Id"]: item for item in observed}
    _require(len(by_id) == len(observed), "duplicate container observations")
    expected = plan["processes"]
    _require(expected and len({item["id"] for item in expected.values()}) == len(expected), "unique process IDs required")
    selected = []
    for role, process in expected.items():
        _require(re.fullmatch(r"[0-9a-f]{64}", process["id"]) and
                 re.fullmatch(r"sha256:[0-9a-f]{64}", process["image"]), "immutable container/image IDs required")
        item = by_id.get(process["id"])
        _require(item is not None and item["Image"] == process["image"], "container/image identity mismatch")
        state = item["State"]
        exit_code = process.get("exit_code", 0)
        _require(exit_code == 0 or (role == "server" and exit_code == 143), "unsupported expected exit status")
        _require(state.get("Status") == "exited" and state.get("ExitCode") == exit_code and
                 not any(state.get(key, True) for key in ("Running", "Paused", "Restarting", "Dead", "OOMKilled")) and
                 state.get("Error") == "" and state.get("FinishedAt", "").startswith("20") and
                 state.get("StartedAt", "").startswith("20"), "process not stopped with its exact expected raw status")
        selected.append({"Id": item["Id"], "Image": item["Image"],
                         "State": {key: state[key] for key in (
                             "Status", "Running", "Paused", "Restarting", "Dead", "OOMKilled", "Error",
                             "ExitCode", "StartedAt", "FinishedAt")},
                         "Mounts": sorted([{key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")}
                                           for mount in item["Mounts"]], key=_json)})
    for role, store in plan["stores"].items():
        _require(store["container"] in {item["id"] for item in expected.values()}, "store owner absent from process pins")
        mounts = [mount for mount in by_id[store["container"]]["Mounts"]
                  if mount["Destination"] == store["destination"]]
        _require(len(mounts) == 1 and mounts[0].get("Type") in ("bind", "volume") and
                 mounts[0].get("Source") == store["source"] and mounts[0].get("RW") is True,
                 f"{role} data mount mismatch")
        destination = PurePosixPath(store["destination"])
        _require(destination.is_absolute() and str(destination) == store["destination"], "invalid mount destination")
        _require(not any(_overlap(PurePosixPath(mount["Destination"]), destination)
                         for mount in by_id[store["container"]]["Mounts"]
                         if mount["Destination"] != store["destination"]), "overlapping/nested data mounts")
    roots = [Path(item["source"]) for item in plan["stores"].values()] + [Path(plan["fence"]), *extra_roots]
    for item in observed:
        if item["State"].get("Running") or item["State"].get("Restarting") or item["State"].get("Paused"):
            _require(not any(_overlap(Path(mount["Source"]), root) for mount in item["Mounts"]
                             if mount.get("Type") in ("bind", "volume") for root in roots),
                     "another running container can access a store, restore target or current fence")
    return sorted(selected, key=lambda item: item["Id"])


def _output(path, roots, protected):
    path = Path(path)
    _require(path.is_absolute() and path.name not in ("", ".", ".."), "absolute output path required")
    parent = _path(path.parent)
    parent_fd = _open_dir(parent)
    try:
        _private_parent(os.fstat(parent_fd))
    finally:
        os.close(parent_fd)
    _require(not any(_overlap(path, other) for other in [*roots.values(), *protected]), "output overlaps protected state")
    _require(not path.exists() and not path.is_symlink(), "output already exists")
    return parent / path.name


def _private_parent(info):
    _require(info.st_uid == os.geteuid(), "output parent owner must be the effective operator UID")
    _require(stat.S_IMODE(info.st_mode) & 0o077 == 0, "output parent must be private with no group/other permissions")


def _private(path):
    parent = _open_dir(path.parent)
    try:
        _private_parent(os.fstat(parent))
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "wb")
    finally:
        os.close(parent)


def _fsync_dir(path):
    fd = _open_dir(path)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _source_file(root, name):
    parts = PurePosixPath(name).parts
    fd = _open_dir(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return os.fdopen(os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd), "rb")
    finally:
        os.close(fd)


def backup(plan, archive_path, receipt_path, *, docker):
    """Archive all three stopped stores. Retain any partial files on failure."""
    roots, fence, credentials = _layout(plan)
    archive = _output(archive_path, roots, [fence.parent, *credentials])
    receipt = _output(receipt_path, roots, [fence.parent, *credentials])
    _require(archive != receipt, "archive and receipt must differ")
    stopped = _cold(plan, docker)
    fence_before = _fence(fence)
    inventory = {role: _inventory(root) for role, root in roots.items()}
    manifest = {"version": 1, "plan": plan, "fence": fence_before, "inventory": inventory,
                "stopped": stopped}
    manifest_raw = _json(manifest)
    _require(len(manifest_raw) <= 64 * 1024 * 1024, "inventory exceeds supported manifest bound")
    with _private(archive) as output:
        with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as bundle:
            header = tarfile.TarInfo("manifest.json")
            header.size = len(manifest_raw)
            header.mode = 0o600
            bundle.addfile(header, io.BytesIO(manifest_raw))
            for role, root in sorted(roots.items()):
                for name, info in sorted(inventory[role]["entries"].items()):
                    header = tarfile.TarInfo(f"stores/{role}" + (f"/{name}" if name else ""))
                    header.mode, header.uid, header.gid = info["mode"], info["uid"], info["gid"]
                    header.mtime = info["mtime_ns"] // 1_000_000_000
                    header.type = tarfile.DIRTYPE if info["kind"] == "dir" else tarfile.REGTYPE
                    header.size = info["size"]
                    if info["kind"] == "file":
                        with _source_file(root, name) as source:
                            _require(_stat_fingerprint(os.fstat(source.fileno())) == inventory[role]["stat_fingerprints"][name], "source changed")
                            bundle.addfile(header, source)
                    else:
                        bundle.addfile(header)
        output.flush()
        os.fsync(output.fileno())
    def confirm(phase):
        _require(_cold(plan, docker) == stopped, f"process/mount observations changed during {phase}; archive is not accepted")
        _require(_fence(fence) == fence_before, f"current fence changed during {phase}; archive is not accepted")
        _require({role: _inventory(root) for role, root in roots.items()} == inventory,
                 f"store contents or identity changed during {phase}; archive is not accepted")
    confirm("backup")
    with archive.open("rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    confirm("backup digest")
    result = {"version": 1, "archive_sha256": archive_hash, "manifest_sha256": _digest(manifest_raw),
              "admissionAuthorized": False, "processCleanupCertified": False,
              "rawExitCodes": {role: next(item["State"]["ExitCode"] for item in stopped
                                         if item["Id"] == process["id"])
                               for role, process in plan["processes"].items()}}
    _fsync_dir(archive.parent)
    with _private(receipt) as output:
        output.write(_json(result))
        output.flush()
        os.fsync(output.fileno())
    _fsync_dir(receipt.parent)
    return result


def _private_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                 stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.geteuid(),
                 "archive/receipt must be operator-owned private regular 0600 files")
        _require(_stat_fingerprint(os.stat(path, follow_symlinks=False)) == _stat_fingerprint(info), "archive/receipt changed")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _unchanged_archive(bundle, sealed):
    _require(all(_stat_fingerprint(os.stat(path, follow_symlinks=False)) == fingerprint
                 for path, fingerprint in sealed.items()) and
             _stat_fingerprint(os.fstat(bundle.fileobj.fileno())) == list(sealed.values())[1],
             "archive or receipt changed during restore")


def _accepted_archive(archive, receipt):
    sealed = {}
    with _private_read(receipt) as receipt_file:
        sealed[receipt] = _stat_fingerprint(os.fstat(receipt_file.fileno()))
        receipt_data = _read_json(receipt_file.read())
        _require(_stat_fingerprint(os.fstat(receipt_file.fileno())) == sealed[receipt], "receipt changed while reading")
    stream = _private_read(archive)
    try:
        sealed[archive] = _stat_fingerprint(os.fstat(stream.fileno()))
        _require(hashlib.file_digest(stream, "sha256").hexdigest() == receipt_data["archive_sha256"], "archive digest mismatch")
        stream.seek(0)
        bundle = tarfile.open(fileobj=stream, mode="r:")
    except BaseException:
        stream.close()
        raise
    try:
        members = bundle.getmembers()
        names = [item.name for item in members]
        _require(len(names) == len(set(names)) and names and names[0] == "manifest.json", "duplicate or missing archive member")
        for item in members:
            path = PurePosixPath(item.name)
            _require(not path.is_absolute() and ".." not in path.parts and str(path) == item.name and
                     (item.isfile() or item.isdir()) and not item.linkname,
                     "unsafe archive member")
        manifest_member = members[0]
        _require(manifest_member.isfile() and manifest_member.size <= 64 * 1024 * 1024, "invalid manifest")
        raw = bundle.extractfile(manifest_member).read()
        _require(_digest(raw) == receipt_data["manifest_sha256"], "manifest digest mismatch")
        manifest = _read_json(raw)
        _require(manifest.get("version") == 1 and receipt_data.get("version") == 1, "unsupported archive version")
        expected = {"manifest.json"}
        for role, inventory in manifest["inventory"].items():
            for name, info in inventory["entries"].items():
                full_name = f"stores/{role}" + (f"/{name}" if name else "")
                expected.add(full_name)
                member = bundle.getmember(full_name)
                _require(info["kind"] in ("dir", "file") and member.isdir() == (info["kind"] == "dir") and
                         member.size == info["size"] and member.mode == info["mode"] and
                         member.uid == info["uid"] and member.gid == info["gid"] and
                         member.mtime == info["mtime_ns"] // 1_000_000_000,
                         "archive metadata mismatch")
                if member.isfile():
                    with bundle.extractfile(member) as source:
                        _require(hashlib.file_digest(source, "sha256").hexdigest() == info["sha256"], "member digest mismatch")
        _require(set(names) == expected, "archive inventory mismatch")
        _unchanged_archive(bundle, sealed)
        return bundle, manifest, sealed
    except BaseException:
        bundle.close()
        stream.close()
        raise


def _metadata(fd, info):
    current = os.fstat(fd)
    if (current.st_uid, current.st_gid) != (info["uid"], info["gid"]):
        os.fchown(fd, info["uid"], info["gid"])
    os.fchmod(fd, info["mode"])
    os.utime(fd, ns=(info["mtime_ns"], info["mtime_ns"]))
    os.fsync(fd)


def restore(plan, archive_path, receipt_path, targets, *, docker):
    """Validate before writing new empty targets. Never rewinds original stores."""
    roots, fence, credentials = _layout(plan)
    archive, receipt = _path(archive_path), _path(receipt_path)
    _require(set(targets) == set(roots), "three explicit targets required")
    target_roots = {role: _path(path) for role, path in targets.items()}
    protected = [*roots.values(), fence.parent, *credentials, archive, receipt]
    for role, target in target_roots.items():
        _require(target.is_dir() and not any(target.iterdir()), "restore target must be an existing empty directory")
        _require(not any(_overlap(target, other) for other in protected), "restore target overlaps protected state")
        _require(not any(_overlap(target, other) for key, other in target_roots.items() if key != role), "overlapping targets")
    stopped = _cold(plan, docker, target_roots.values())
    bundle, manifest, sealed = _accepted_archive(archive, receipt)
    target_fds = {}
    try:
        _require(manifest["plan"] == plan and manifest["stopped"] == stopped, "archive plan/process identities mismatch")
        _require(_fence(fence) == manifest["fence"], "independent current fence mismatch")
        _require({role: _inventory(root) for role, root in roots.items()} == manifest["inventory"],
                 "current stores advanced or changed; automatic data rollback refused")
        _unchanged_archive(bundle, sealed)
        # Validate all targets before writing any one of them; keep descriptors
        # pinned so a renamed path cannot redirect a later file creation.
        for role, target in target_roots.items():
            target_fds[role] = _open_dir(target)
            _require(not os.listdir(target_fds[role]), "restore target changed")
        for role, target in target_roots.items():
            inventory = manifest["inventory"][role]["entries"]
            fds = {"": os.dup(target_fds[role])}
            try:
                _require(not os.listdir(fds[""]), "restore target changed")
                for name, info in sorted(inventory.items(), key=lambda pair: (len(PurePosixPath(pair[0]).parts), pair[0])):
                    if not name:
                        continue
                    parent_name, _, basename = name.rpartition("/")
                    parent = fds[parent_name]
                    if info["kind"] == "dir":
                        os.mkdir(basename, 0o700, dir_fd=parent)
                        fds[name] = os.open(basename, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    else:
                        fd = os.open(basename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                        try:
                            with bundle.extractfile(f"stores/{role}/{name}") as source, os.fdopen(os.dup(fd), "wb") as destination:
                                while chunk := source.read(1024 * 1024):
                                    destination.write(chunk)
                            _metadata(fd, info)
                        finally:
                            os.close(fd)
                for name in sorted(fds, key=lambda value: len(PurePosixPath(value).parts), reverse=True):
                    _metadata(fds[name], inventory[name])
            finally:
                for fd in fds.values():
                    os.close(fd)
            _fsync_dir(target.parent)
        _require(all((os.stat(target, follow_symlinks=False).st_dev, os.stat(target, follow_symlinks=False).st_ino) ==
                     (os.fstat(target_fds[role]).st_dev, os.fstat(target_fds[role]).st_ino)
                     for role, target in target_roots.items()), "restore target identity changed")
        _require(all(_inventory(target)["entries"] == manifest["inventory"][role]["entries"]
                     for role, target in target_roots.items()), "clone verification failed; do not start it")
        _require(_cold(plan, docker, target_roots.values()) == stopped and _fence(fence) == manifest["fence"] and
                 {role: _inventory(root) for role, root in roots.items()} == manifest["inventory"],
                 "original state changed during restore; retain partial clone for owner review")
        _unchanged_archive(bundle, sealed)
        return {"version": 1, "restored": {role: str(path) for role, path in target_roots.items()},
                "productionWritesEnabled": False, "admissionAuthorized": False,
                "processCleanupCertified": False}
    finally:
        for fd in target_fds.values():
            os.close(fd)
        bundle.close()
        bundle.fileobj.close()


class Docker:
    """Live local Linux/rootful Docker adapter; observations omit credentials."""

    @staticmethod
    def _run(*args):
        result = subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=30)
        return result.stdout

    def __init__(self):
        _require(platform.system() == "Linux" and platform.machine() in ("x86_64", "amd64") and os.geteuid() == 0,
                 "operator CLI requires Linux amd64 and root for exact ownership")
        _require(not os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"), "Docker endpoint overrides unsupported")
        context = _read_json(self._run("context", "inspect"))
        _require(len(context) == 1 and context[0]["Endpoints"]["docker"]["Host"] == "unix:///var/run/docker.sock",
                 "only local rootful Docker socket supported")
        info = _read_json(self._run("info", "--format", "{{json .}}"))
        _require(info.get("OSType") == "linux" and info.get("Architecture") in ("x86_64", "amd64") and
                 not any("rootless" in value or "userns" in value for value in info.get("SecurityOptions", [])) and
                 "docker desktop" not in info.get("OperatingSystem", "").lower(), "unsupported Docker environment")

    def __call__(self):
        ids = self._run("ps", "-aq", "--no-trunc").split()
        if not ids:
            return []
        state_keys = ("Status", "Running", "Paused", "Restarting", "Dead", "OOMKilled", "Error",
                      "ExitCode", "StartedAt", "FinishedAt")
        state = ",".join('"' + key + '":{{json .State.' + key + '}}' for key in state_keys)
        template = '{"Id":{{json .Id}},"Image":{{json .Image}},"State":{' + state + '},"Mounts":{{json .Mounts}}}'
        return [_read_json(line) for line in self._run("inspect", "--format", template, *ids).splitlines()]


def _local_storage(paths):
    """Operator-only Linux check; fixture adapters do not claim this host proof."""
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        encoded = left.split()[4]
        mount = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), encoded))
        mounts.append((mount, right.split()[0]))
    for value in paths:
        path = _path(value)
        candidates = [(mount, kind) for mount, kind in mounts if path == mount or mount in path.parents]
        _require(candidates, "cannot establish local filesystem")
        _, kind = max(candidates, key=lambda item: len(item[0].parts))
        _require(kind in ("ext4", "xfs"), "operator capture supports local ext4/XFS only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--targets", type=Path, help="JSON object mapping server/bridge/mongo to existing empty paths")
    args = parser.parse_args()
    try:
        docker = Docker()
        plan = _read_json(args.plan.read_bytes())
        roots, fence, credentials = _layout(plan)
        targets = _read_json(args.targets.read_bytes()) if args.targets else {}
        _local_storage([*roots.values(), fence, *credentials, args.archive.parent,
                        args.receipt.parent, *targets.values()])
        if args.operation == "backup":
            _require(args.targets is None, "backup does not accept targets")
            result = backup(plan, args.archive, args.receipt, docker=docker)
        else:
            _require(args.targets is not None, "restore requires targets")
            result = restore(plan, args.archive, args.receipt, targets, docker=docker)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        # Do not print Docker stderr, source bytes or credential-bearing settings.
        print(f"cold-state refused: {error if isinstance(error, Refused) else type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
