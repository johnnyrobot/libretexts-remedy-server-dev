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


def image(tmp_path, corrupt_layer=False):
    layer = b"known synthetic layer bytes"
    digest = hashlib.sha256(layer).hexdigest()
    config = json.dumps({"architecture": "amd64", "os": "linux", "rootfs": {"type": "layers", "diff_ids": ["sha256:" + digest]}}).encode()
    config_id = hashlib.sha256(config).hexdigest()
    manifest = json.dumps([{"Config": config_id + ".json", "RepoTags": ["candidate:test"], "Layers": ["layer.tar"]}]).encode()
    path = tmp_path / "image.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [("manifest.json", manifest), (config_id + ".json", config), ("layer.tar", b"changed" if corrupt_layer else layer)]:
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
