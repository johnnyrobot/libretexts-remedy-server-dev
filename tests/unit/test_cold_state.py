"""Storage seam tests; controlled Docker data is not Linux service acceptance."""
import importlib.util
from pathlib import Path
import os

import pytest

MODULE = Path(__file__).resolve().parents[2] / "deploy/stack/cold_state.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("cold_state", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cold(tmp_path):
    stores = {}
    containers = []
    expected = {}
    for index, role in enumerate(("server", "bridge", "mongo"), 1):
        source = tmp_path / role
        source.mkdir(mode=0o700)
        container = str(index) * 64
        image = "sha256:" + str(index + 3) * 64
        stores[role] = {"source": str(source), "container": container, "destination": "/data"}
        containers.append({"Id": container, "Image": image, "State": {
            "Status": "exited", "Running": False, "Paused": False, "Restarting": False,
            "Dead": False, "OOMKilled": False, "Error": "", "ExitCode": 0,
            "StartedAt": "2026-10-30T01:00:00Z", "FinishedAt": "2026-10-30T01:01:00Z"},
            "Mounts": [{"Type": "bind", "Source": str(source), "Destination": "/data", "RW": True}]})
        expected[role] = {"id": container, "image": image}
    trust = tmp_path / "trust"
    trust.mkdir(mode=0o700)
    fence = trust / "current-fence"
    fence.write_bytes(b"independent-current-epoch-7")
    fence.chmod(0o600)
    keys = tmp_path / "credentials"
    keys.mkdir(mode=0o700)
    (keys / "key").write_bytes(b"fixture key must stay outside archive")
    plan = {"version": 1, "stores": stores, "processes": expected,
            "fence": str(fence), "credential_roots": [str(keys)]}
    return plan, lambda: containers, tmp_path


def test_cold_clone_preserves_full_private_files_and_markers(cold):
    helper = load_helper()
    plan, docker, root = cold
    files = {"server": {"jobs.sqlite": b"sqlite bytes", "jobs.sqlite-wal": b"wal bytes",
                        "input/source.pdf": b"private pdf", "options.json": b'{"mode":"strict"}',
                        "unresolved/owner.lock": b"retain lock and unresolved ownership"},
             "bridge": {"ledger.sqlite-wal": b"bridge wal", "snapshot/page.html": b"private snapshot",
                        "audit/history.json": b'{"actor":"fixture","outcome":"unknown"}'},
             "mongo": {"WiredTiger": b"mongo bytes", "journal/WiredTigerLog.00001": b"journal"}}
    for role, values in files.items():
        for name, content in values.items():
            path = Path(plan["stores"][role]["source"]) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o600)
            os.utime(path, ns=(1700000000000000123, 1700000000000000123))
    archive, receipt = root / "backup.tar", root / "receipt.json"
    helper.backup(plan, archive, receipt, docker=docker)
    targets = {role: root / (role + "-clone") for role in files}
    for target in targets.values():
        target.mkdir(mode=0o700)
    helper.restore(plan, archive, receipt, targets, docker=docker)
    for role, values in files.items():
        for name, content in values.items():
            source = Path(plan["stores"][role]["source"]) / name
            copy = targets[role] / name
            assert copy.read_bytes() == content
            assert (copy.stat().st_mode, copy.stat().st_uid, copy.stat().st_gid, copy.stat().st_mtime_ns) == (
                source.stat().st_mode, source.stat().st_uid, source.stat().st_gid, source.stat().st_mtime_ns)
    assert archive.stat().st_mode & 0o777 == 0o600
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert Path(plan["fence"]).read_bytes() == b"independent-current-epoch-7"


def test_server_sigterm_capture_requires_exact_role_expectation_and_never_certifies_cleanup(cold):
    helper = load_helper()
    plan, docker, root = cold
    docker()[0]["State"]["ExitCode"] = 143
    with pytest.raises(helper.Refused, match="stopped"):
        helper.backup(plan, root / "refused.tar", root / "refused.json", docker=docker)
    plan["processes"]["server"]["exit_code"] = 143
    result = helper.backup(plan, root / "capture.tar", root / "capture.json", docker=docker)
    assert result["processCleanupCertified"] is False
    assert result["admissionAuthorized"] is False
    assert result["rawExitCodes"]["server"] == 143


def test_restore_refuses_target_mounted_by_another_running_container(cold):
    helper = load_helper()
    plan, docker, root = cold
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    targets = {role: root / (role + "-clone") for role in plan["stores"]}
    for path in targets.values():
        path.mkdir()
    docker().append({"Id": "f" * 64, "Image": "sha256:" + "e" * 64,
                     "State": {"Running": True}, "Mounts": [
                         {"Type": "bind", "Source": str(targets["mongo"]), "Destination": "/data"}]})
    with pytest.raises(helper.Refused, match="running"):
        helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=docker)
    assert all(not list(path.iterdir()) for path in targets.values())


def test_nested_data_mount_refuses_ambiguous_store_inventory(cold):
    helper = load_helper()
    plan, docker, root = cold
    docker()[0]["Mounts"].append({"Type": "bind", "Source": str(root / "credentials"),
                                  "Destination": "/data/hidden", "RW": False})
    with pytest.raises(helper.Refused, match="mount"):
        helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    assert not (root / "backup.tar").exists()


def clone_targets(plan, root):
    targets = {role: root / (role + "-clone") for role in plan["stores"]}
    for path in targets.values():
        path.mkdir(mode=0o700)
    return targets


def test_fence_and_credentials_are_excluded_and_changed_fence_refuses_restore(cold):
    import tarfile
    helper = load_helper()
    plan, docker, root = cold
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    with tarfile.open(root / "backup.tar") as archive:
        assert archive.getnames() == ["manifest.json", "stores/bridge", "stores/mongo", "stores/server"]
        assert b"independent-current-epoch-7" not in (root / "backup.tar").read_bytes()
        assert b"fixture key must stay outside archive" not in (root / "backup.tar").read_bytes()
    Path(plan["fence"]).write_bytes(b"advanced-epoch-8")
    targets = clone_targets(plan, root)
    with pytest.raises(helper.Refused, match="fence mismatch"):
        helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=docker)
    assert Path(plan["fence"]).read_bytes() == b"advanced-epoch-8"
    assert all(not list(path.iterdir()) for path in targets.values())


@pytest.mark.parametrize("change", ["new_history", "same_bytes_rewritten", "nonempty_target"])
def test_restore_never_erases_new_current_state_or_nonempty_targets(cold, change):
    helper = load_helper()
    plan, docker, root = cold
    source = Path(plan["stores"]["bridge"]["source"]) / "history"
    source.write_bytes(b"original history")
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    targets = clone_targets(plan, root)
    if change == "new_history":
        source.write_bytes(b"newer unknown outcome must survive")
    elif change == "same_bytes_rewritten":
        old = source.stat()
        source.write_bytes(b"original history")
        os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    else:
        (targets["server"] / "keep").write_bytes(b"new current data")
    before = source.read_bytes()
    with pytest.raises(helper.Refused, match="advanced|empty"):
        helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=docker)
    assert source.read_bytes() == before
    assert not list(targets["bridge"].iterdir())
    if change == "nonempty_target":
        assert (targets["server"] / "keep").read_bytes() == b"new current data"


@pytest.mark.parametrize("state", ["Running", "Paused", "Restarting", "Dead", "OOMKilled", "Error", "ExitCode", "Image", "Source"])
def test_cold_capture_refuses_incorrect_process_or_mount_evidence(cold, state):
    helper = load_helper()
    plan, docker, root = cold
    container = docker()[1]
    if state == "Image":
        container["Image"] = "sha256:" + "f" * 64
    elif state == "Source":
        container["Mounts"][0]["Source"] = str(root)
    else:
        container["State"][state] = "unclean stop" if state == "Error" else (137 if state == "ExitCode" else True)
    with pytest.raises(helper.Refused):
        helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    assert not (root / "backup.tar").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "fence_in_data", "credentials_in_data"])
def test_capture_rejects_unsafe_store_layout_without_reading_private_aliases(cold, kind):
    helper = load_helper()
    plan, docker, root = cold
    source = Path(plan["stores"]["server"]["source"])
    if kind == "symlink":
        (source / "unsafe").symlink_to(Path(plan["fence"]))
    elif kind == "hardlink":
        os.link(Path(plan["credential_roots"][0]) / "key", source / "unsafe")
    elif kind == "fifo":
        os.mkfifo(source / "unsafe")
    elif kind == "fence_in_data":
        fence = source / "fence"
        fence.write_bytes(b"must not archive")
        plan["fence"] = str(fence)
    else:
        plan["credential_roots"] = [str(source)]
    with pytest.raises(helper.Refused):
        helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    assert not (root / "receipt.json").exists()


def rewrite_archive(root, mutate):
    """Reseal the outer checksum so individual inventory validation is exercised."""
    import hashlib
    import io
    import json
    import tarfile
    archive = root / "backup.tar"
    with tarfile.open(archive) as source:
        members = [(item, source.extractfile(item).read() if item.isfile() else None) for item in source.getmembers()]
    mutate(members)
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as destination:
        for item, content in members:
            destination.addfile(item, io.BytesIO(content) if content is not None else None)
    receipt = root / "receipt.json"
    data = json.loads(receipt.read_text())
    data["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(data))


@pytest.mark.parametrize("attack", ["content", "traversal", "duplicate", "symlink", "hardlink"])
def test_entire_archive_is_validated_before_any_restore_write(cold, attack):
    import tarfile
    helper = load_helper()
    plan, docker, root = cold
    (Path(plan["stores"]["mongo"]["source"]) / "journal").write_bytes(b"last member contents")
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    def mutate(members):
        if attack == "content":
            index = next(i for i, (item, _) in enumerate(members) if item.name.endswith("/journal"))
            item, raw = members[index]
            members[index] = item, b"X" * len(raw)
        elif attack == "duplicate":
            members.append(members[-1])
        else:
            item = tarfile.TarInfo("../../escaped" if attack == "traversal" else "stores/server/alias")
            if attack in ("symlink", "hardlink"):
                item.type = tarfile.SYMTYPE if attack == "symlink" else tarfile.LNKTYPE
                item.linkname = "../../escaped"
            members.append((item, b"" if item.isfile() else None))
    rewrite_archive(root, mutate)
    targets = clone_targets(plan, root)
    with pytest.raises(helper.Refused, match="digest|unsafe|duplicate"):
        helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=docker)
    assert all(not list(path.iterdir()) for path in targets.values())
    assert not (root.parent / "escaped").exists()


def test_backup_detects_fence_and_inventory_changes_without_issuing_acceptance_receipt(cold):
    helper = load_helper()
    plan, observe, root = cold
    calls = 0
    def docker():
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(plan["fence"]).write_bytes(b"advanced during backup")
            (Path(plan["stores"]["server"]["source"]) / "new-claim").write_bytes(b"unknown")
        return observe()
    with pytest.raises(helper.Refused, match="changed during backup"):
        helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    assert (root / "backup.tar").exists()  # Retain incomplete evidence; never clean it up.
    assert not (root / "receipt.json").exists()


def test_operator_cli_refuses_mac_without_contacting_docker(cold, monkeypatch):
    helper = load_helper()
    monkeypatch.setattr(helper.platform, "system", lambda: "Darwin")
    with pytest.raises(helper.Refused, match="Linux amd64"):
        helper.Docker()


def test_concurrent_archive_replacement_refuses_success_even_after_copy(cold):
    helper = load_helper()
    plan, observe, root = cold
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=observe)
    targets = clone_targets(plan, root)
    calls = 0
    def docker():
        nonlocal calls
        calls += 1
        if calls == 2:
            archive = root / "backup.tar"
            original = archive.read_bytes()
            archive.write_bytes(original[:-1] + b"X")
        return observe()
    with pytest.raises(helper.Refused, match="archive.*changed"):
        helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=docker)


def test_copy_failure_retains_partial_evidence_and_never_changes_originals(cold):
    helper = load_helper()
    plan, docker, root = cold
    for role in plan["stores"]:
        (Path(plan["stores"][role]["source"]) / "private").write_bytes((role + " original").encode())
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    targets = clone_targets(plan, root)
    # A readonly target directory would not reliably fail under root. Instead a
    # filesystem adapter adds an unexpected target entry at the first Docker read.
    def racing_docker():
        (targets["mongo"] / "unexpected").write_bytes(b"must preserve")
        return docker()
    with pytest.raises(helper.Refused, match="target changed"):
        helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=racing_docker)
    assert (targets["mongo"] / "unexpected").read_bytes() == b"must preserve"
    assert not list(targets["bridge"].iterdir())
    assert not list(targets["server"].iterdir())
    for role in plan["stores"]:
        assert (Path(plan["stores"][role]["source"]) / "private").read_bytes() == (role + " original").encode()


def test_unknown_plan_fields_are_never_serialized_into_archive(cold):
    helper = load_helper()
    plan, docker, root = cold
    plan["accidental_credential"] = "must not become an archive payload"
    with pytest.raises(helper.Refused, match="plan fields"):
        helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    assert not (root / "backup.tar").exists()


def test_unrelated_docker_health_logs_are_never_archived(cold):
    helper = load_helper()
    plan, docker, root = cold
    docker()[0]["State"]["Health"] = {"Log": [{"Output": "UNRELATED_PRIVATE_RUNTIME_OUTPUT"}]}
    helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
    assert b"UNRELATED_PRIVATE_RUNTIME_OUTPUT" not in (root / "backup.tar").read_bytes()


@pytest.mark.parametrize("mount_parent", [False, True])
@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_cold_operation_refuses_running_container_with_only_current_fence_access(cold, mount_parent, operation):
    helper = load_helper()
    plan, docker, root = cold
    # Keep the fence's parent separate from every store so both cases exercise
    # fence-only access rather than an ancestor mount already covering stores.
    trust = root / "independent-trust"
    trust.mkdir(mode=0o700)
    fence = trust / "current-fence"
    fence.write_bytes(Path(plan["fence"]).read_bytes())
    fence.chmod(0o600)
    plan["fence"] = str(fence)
    original_bytes, original_stat = fence.read_bytes(), fence.stat()
    targets = None
    if operation == "restore":
        helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
        targets = clone_targets(plan, root)
    docker().append({"Id": "f" * 64, "Image": "sha256:" + "e" * 64,
                     "State": {"Running": True}, "Mounts": [
                         {"Type": "bind", "Source": str(fence.parent if mount_parent else fence),
                          "Destination": "/independent-fence", "RW": True}]})
    with pytest.raises(helper.Refused, match="running"):
        if operation == "backup":
            helper.backup(plan, root / "backup.tar", root / "receipt.json", docker=docker)
        else:
            helper.restore(plan, root / "backup.tar", root / "receipt.json", targets, docker=docker)
    assert fence.read_bytes() == original_bytes
    assert (fence.stat().st_dev, fence.stat().st_ino, fence.stat().st_ctime_ns) == (
        original_stat.st_dev, original_stat.st_ino, original_stat.st_ctime_ns)
    if operation == "backup":
        assert not (root / "backup.tar").exists()
        assert not (root / "receipt.json").exists()
    else:
        assert all(not list(path.iterdir()) for path in targets.values())


@pytest.mark.parametrize("wrong_owner", [False, True])
def test_capture_refuses_public_or_wrong_owner_output_parent(cold, monkeypatch, wrong_owner):
    helper = load_helper()
    plan, docker, root = cold
    output = root / "output"
    output.mkdir(mode=0o700)
    if wrong_owner:
        monkeypatch.setattr(helper.os, "geteuid", lambda: output.stat().st_uid + 1)
    else:
        output.chmod(0o755)
    with pytest.raises(helper.Refused, match="parent.*private|parent.*owner"):
        helper.backup(plan, output / "backup.tar", output / "receipt.json", docker=docker)
    assert not list(output.iterdir())


@pytest.mark.parametrize("field", ["archive", "receipt"])
@pytest.mark.parametrize("wrong_owner", [False, True])
def test_restore_refuses_public_or_wrong_owner_evidence_files(cold, monkeypatch, field, wrong_owner):
    helper = load_helper()
    plan, docker, root = cold
    archive, receipt = root / "backup.tar", root / "receipt.json"
    helper.backup(plan, archive, receipt, docker=docker)
    targets = clone_targets(plan, root)
    evidence = archive if field == "archive" else receipt
    if wrong_owner:
        # Model a consistently wrong owner through the filesystem interface;
        # no real chown or privileged test process is required.
        from types import SimpleNamespace
        original_fstat, original_stat = helper.os.fstat, helper.os.stat
        identity = evidence.stat().st_dev, evidence.stat().st_ino
        def wrong_owner_stat(info):
            if (info.st_dev, info.st_ino) == identity:
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                fields["st_uid"] += 1
                return SimpleNamespace(**fields)
            return info
        monkeypatch.setattr(helper.os, "fstat", lambda fd: wrong_owner_stat(original_fstat(fd)))
        monkeypatch.setattr(helper.os, "stat", lambda *args, **kwargs: wrong_owner_stat(original_stat(*args, **kwargs)))
    else:
        evidence.chmod(0o644)
    with pytest.raises(helper.Refused, match="owner|private regular"):
        helper.restore(plan, archive, receipt, targets, docker=docker)
    assert all(not list(path.iterdir()) for path in targets.values())


@pytest.mark.parametrize("operation", ["archive", "receipt", "restore"])
def test_fence_parent_is_reserved_from_backup_and_restore_placement(cold, operation):
    helper = load_helper()
    plan, docker, root = cold
    fence = Path(plan["fence"])
    before = fence.read_bytes(), fence.stat()
    archive, receipt = root / "backup.tar", root / "receipt.json"
    targets = None
    if operation == "restore":
        helper.backup(plan, archive, receipt, docker=docker)
        targets = clone_targets(plan, root)
        targets["bridge"] = fence.parent / "sibling-clone"
        targets["bridge"].mkdir(mode=0o700)
    elif operation == "archive":
        archive = fence.parent / "sibling-backup.tar"
    else:
        receipt = fence.parent / "sibling-receipt.json"
    with pytest.raises(helper.Refused, match="overlap"):
        if operation == "restore":
            helper.restore(plan, archive, receipt, targets, docker=docker)
        else:
            helper.backup(plan, archive, receipt, docker=docker)
    assert fence.read_bytes() == before[0]
    assert (fence.stat().st_dev, fence.stat().st_ino, fence.stat().st_ctime_ns) == (
        before[1].st_dev, before[1].st_ino, before[1].st_ctime_ns)
    if operation == "restore":
        assert all(not list(path.iterdir()) for path in targets.values())
    else:
        assert not archive.exists()
        assert not receipt.exists()
