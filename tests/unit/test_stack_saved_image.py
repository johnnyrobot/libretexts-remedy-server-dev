"""Saved-image import must reject changed archive/config/layer bytes."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    sys.path.insert(0, str(ROOT / '.github/stack-proof'))
    spec = importlib.util.spec_from_file_location("conductor_artifacts", ROOT / ".github/stack-proof/conductor_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('damage', [None, 'changed', 'missing', 'symlink', 'existing-output'])
def test_packaged_original_zip_uses_exact_bytes_without_network_or_overwrite(tmp_path, monkeypatch, damage):
    module = load()
    def network_forbidden(*args, **kwargs):
        raise AssertionError('sealed originals must not require a network credential')
    monkeypatch.setattr(module, 'build_opener', network_forbidden)
    directory = tmp_path / 'package' / 'release-2.156.2'
    directory.mkdir(parents=True)
    raw = b'original synthetic ZIP bytes; acquisition fixture only'
    source = directory / 'original-artifact.zip'
    source.write_bytes(raw)
    target = {'target': 'release-2.156.2', 'validation': {'artifactDigest': 'sha256:' + hashlib.sha256(raw).hexdigest()}}
    destination = tmp_path / 'copied.zip'
    if damage == 'changed': source.write_bytes(raw + b'tampered')
    elif damage == 'missing': source.unlink()
    elif damage == 'symlink':
        original = directory / 'original';source.rename(original);source.symlink_to(original)
    elif damage == 'existing-output': destination.write_bytes(b'retain previous evidence')
    if damage is None:
        module.acquire_original_zip(destination, target, tmp_path / 'package')
        assert destination.read_bytes() == raw
    else:
        with pytest.raises((ValueError, FileExistsError)):
            module.acquire_original_zip(destination, target, tmp_path / 'package')
        if damage == 'existing-output': assert destination.read_bytes() == b'retain previous evidence'
        else: assert not destination.exists()


def image(tmp_path, corrupt_layer=False):
    layer = b"known synthetic layer bytes"
    digest = hashlib.sha256(layer).hexdigest()
    config = json.dumps({"architecture": "amd64", "os": "linux", "rootfs": {"type": "layers", "diff_ids": ["sha256:" + digest]}}).encode()
    config_id = hashlib.sha256(config).hexdigest()
    manifest = json.dumps([{"Config": config_id + ".json", "RepoTags": ["candidate:test"], "Layers": ["layer.tar"]}]).encode()
    oci = json.dumps({'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json',
        'config':{'digest':'sha256:'+config_id,'size':len(config)},
        'layers':[{'mediaType':'application/vnd.oci.image.layer.v1.tar','digest':'sha256:'+digest,'size':len(layer)}]}).encode()
    oci_id = hashlib.sha256(oci).hexdigest()
    index = json.dumps({'schemaVersion':2,'manifests':[{'digest':'sha256:'+oci_id,'size':len(oci)}]}).encode()
    path = tmp_path / "image.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [("manifest.json", manifest), (config_id + ".json", config), ("layer.tar", b"changed" if corrupt_layer else layer), ("index.json", index), ("blobs/sha256/"+oci_id, oci)]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path, "sha256:" + config_id


def test_saved_image_binds_exact_config_and_uncompressed_layers(tmp_path):
    path, image_id = image(tmp_path)
    value = load().verify_saved_image(path, image_id)
    assert value["imageID"] == image_id
    assert len(value["filesystemDiffIDs"]) == 1


def test_saved_image_refuses_changed_layer_under_original_config(tmp_path):
    path, image_id = image(tmp_path, corrupt_layer=True)
    with pytest.raises(ValueError, match="layer digest"):
        load().verify_saved_image(path, image_id)


def test_saved_image_refuses_different_config_id(tmp_path):
    path, _ = image(tmp_path)
    with pytest.raises(ValueError, match="config digest"):
        load().verify_saved_image(path, "sha256:" + "0" * 64)


def test_loaded_identity_mapping_binds_runtime_instead_of_assuming_config_id(tmp_path):
    module = load()
    path, image_id = image(tmp_path)
    source = module.verify_saved_image(path, image_id)
    actual = {'Id': source['sourceManifestDigest'], 'Architecture': 'amd64', 'Os': 'linux',
              'RootFS': {'Type': 'layers', 'Layers': source['filesystemDiffIDs']}, 'Config': {}}
    mapping = module.verify_loaded_image(source, actual)
    assert mapping['sourceConfigDigest'] == image_id
    assert mapping['loadedDockerImageID'] == actual['Id']
    assert mapping['identityChanged'] is True


@pytest.mark.parametrize('change', ['layers', 'config', 'unknown', 'platform', 'identity'])
def test_loaded_identity_mapping_rejects_tag_substitution(tmp_path, change):
    module = load()
    path, image_id = image(tmp_path)
    source = module.verify_saved_image(path, image_id)
    actual = {'Id': image_id, 'Architecture': 'amd64', 'Os': 'linux',
              'RootFS': {'Type': 'layers', 'Layers': source['filesystemDiffIDs']}, 'Config': {}}
    if change == 'layers': actual['RootFS']['Layers'] = ['sha256:' + 'b' * 64]
    if change == 'config': actual['Config'] = {'Entrypoint': ['different-command']}
    if change == 'unknown': actual['Config'] = {'FutureExecutionSetting': True}
    if change == 'platform': actual['Architecture'] = 'arm64'
    if change == 'identity': actual['Id'] = 'mutable:tag'
    with pytest.raises(ValueError):
        module.verify_loaded_image(source, actual)


def test_loaded_mapping_refuses_an_identity_outside_original_archive(tmp_path):
    module = load()
    path, image_id = image(tmp_path)
    source = module.verify_saved_image(path, image_id)
    actual = {'Id': 'sha256:' + 'e' * 64, 'Architecture': 'amd64', 'Os': 'linux',
              'RootFS': {'Type': 'layers', 'Layers': source['filesystemDiffIDs']}, 'Config': {}}
    with pytest.raises(ValueError, match='archive identity'):
        module.verify_loaded_image(source, actual)
