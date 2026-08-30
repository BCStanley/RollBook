import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelEntry:
    name: str
    version: str
    asset_url: str
    checksum: str # SHA-256 hex


@dataclass(frozen=True)
class ModelManifest:
    segmentation_models: tuple[ModelEntry, ...]
    recognition_models: tuple[ModelEntry, ...]


class ManifestError(Exception):
    pass


def load_model_entry(raw_dict: dict[str, object]) -> ModelEntry:
    try:
        name = raw_dict["name"]
        version = raw_dict["version"]
        asset_url = raw_dict["asset_url"]
        checksum = raw_dict["checksum"]
    except KeyError as missing:
        raise ManifestError(f"Malformed dict in ModelManifest, missing {missing}") from missing
    if not isinstance(name, str):
        raise ManifestError(f"dict key \"name\": {name} in ModelEntry must be str")
    if not isinstance(version, str):
        raise ManifestError(f"dict key \"version\": {version} in ModelEntry must be str")
    if not isinstance(asset_url, str):
        raise ManifestError(f"dict key \"asset_url\": {asset_url} in ModelEntry must be str")
    if not isinstance(checksum, str):
        raise ManifestError(f"dict key \"checksum\": {checksum} in ModelEntry must be str")
    return ModelEntry(
        name=name,
        version=version,
        asset_url=asset_url,
        checksum=checksum
    )


def load_manifest(file_path: Path) -> ModelManifest:

    try:
        with file_path.open(encoding="utf8") as f:
            raw = json.load(f)
    except Exception as e:
        raise ManifestError(f"{file_path} could not be loaded: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestError(f"{file_path}: expected a JSON object")

    segmentation_models: tuple[ModelEntry, ...] = ()
    recognition_models: tuple[ModelEntry, ...] = ()

    try:
        for item in raw["segmentation_models"]:
            segmentation_models += load_model_entry(item),
        for item in raw["recognition_models"]:
            recognition_models += load_model_entry(item),
    except Exception as e:
        raise ManifestError(f"{file_path}: could not all ModelEntries: {e}") from e
    return ModelManifest(
        segmentation_models=segmentation_models,
        recognition_models=recognition_models
    )


def generate_checksum(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_checksum(file_path: Path, expected_checksum: str) -> bool:
    try:
        new_checksum = generate_checksum(file_path)
    except Exception as e:
        raise ManifestError(f"Could not create hash of file {file_path}: {e}") from e
    return(new_checksum == expected_checksum)


def fetch_model(url: str, destination: Path) -> None: 
    with urlopen(url, timeout=30) as response, open(destination, mode="wb") as f:
        for chunk in iter(lambda: response.read(8192), b""):
                f.write(chunk)


def ensure_model_cached(entry: ModelEntry,
                        cache_dir: Path,
                        fetch: Callable[[str, Path], None] = fetch_model) -> Path:
    # Check if model with correct name in cache_dir.
    cache_dir.mkdir(parents=True, exist_ok=True)
    expected_path: Path = cache_dir / f"{entry.name}-{entry.version}.mlmodel"
    if expected_path.exists(): # It does: verify_checksum.
        if verify_checksum(expected_path, entry.checksum):
            return expected_path # checksum correct, return that.
        else: # It's not, this is the complex part.
            found_checksum: str = generate_checksum(expected_path)
            new_name: Path = (
            cache_dir / f"DUPLICATE_{found_checksum[:8]}_{entry.name}-{entry.version}.mlmodel"
            )
            os.rename(expected_path, new_name) # rename the old file.
            try:
                fetch(entry.asset_url, expected_path)
            except Exception as e:
                if expected_path.exists():
                    os.remove(expected_path)
                raise ManifestError(f"""
                Could not fetch model {entry.name}-{entry.version}
                from {entry.asset_url}: {e}""") from e
            if verify_checksum(expected_path, entry.checksum): # Check new checksum matches
                return expected_path # If so, return that.
            else:
                os.remove(expected_path)
                raise ManifestError(f"""
                Model {entry.name}-{entry.version} from {entry.asset_url}:
                does not match checksum {entry.checksum}. Possible network issue or corrupted file.
                Fetched file removed.""")

    # It doesnt: fetch it.
    try:
        fetch(entry.asset_url, expected_path)
    except Exception as e:
        if expected_path.exists():
            os.remove(expected_path)
        raise ManifestError(f"""
        Could not fetch model {entry.name}-{entry.version} 
        from {entry.asset_url}: {e}""") from e
    if verify_checksum(expected_path, entry.checksum): # Check that the checksum matches
        return expected_path # if so, return that.
    else:
        os.remove(expected_path)
        raise ManifestError(f"""
        Model {entry.name}-{entry.version} from {entry.asset_url}:
        does not match checksum {entry.checksum}. Possible network issue or corrupted file.
        Fetched file removed.""")

