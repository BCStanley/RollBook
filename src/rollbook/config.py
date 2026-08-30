from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ABBREV_MAP_FILENAME = "abbrev_map.json"
REPORTER_MAP_FILENAME = "reporters.json"
SPELL_MAP_FILENAME = "spell.json"
COMPANY_MAP_FILENAME = "companies.json"


@dataclass(frozen=True)
class RegexMap:
    patterns: dict[re.Pattern[str], str]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ReporterEntry:
    canonical_abbrev: str
    vols: int | None
    er_vol: tuple[int, ...]
    series: tuple[str, ...]


@dataclass(frozen=True)
class ReporterMap:
    entries: dict[str, ReporterEntry]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Config: 
    abbrev_map: RegexMap
    company_abbrev: RegexMap
    spelling_variants: RegexMap
    reporter_map: ReporterMap


class ConfigError(Exception):
    pass


def load_regex_map(path: Path) -> RegexMap:

    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        raise ConfigError(f"{path} could not be loaded: {e}")

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a JSON object")

    patterns: dict[re.Pattern[str], str] = {}
    warnings: tuple[str, ...] = ()

    for key, value in raw.items():
        try:
            compiled = re.compile(key)
            if isinstance(value, str):
                patterns[compiled] = value
            else:
                warnings += f"{key}: {value}, value must be str",
        except re.error as e:
            warnings += f"{key}: {e}",

    return RegexMap(patterns=patterns, warnings=warnings)


def load_reporter_map(path: Path) -> ReporterMap:
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        raise ConfigError(f"{path} could not be loaded: {e}")

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a JSON object")

    entries: dict[str, ReporterEntry] = {}
    warnings: tuple[str, ...] = ()

    for key, value in raw.items():
        if not isinstance(value, dict):
            warnings += f"ReporterEntry for {key} is malformed",
            continue
        try:
            canonical_abbrev = value["canonical_abbrev"]
            vols = value["vols"]
            er_vol = value["er_vol"]
            series = value["series"]
        except KeyError as missing:
            warnings += f"ReporterEntry {key} missing: {missing}",
            continue
        if not isinstance(canonical_abbrev, str):
            warnings += f"ReporterEntry {key}: canonical_abbrev must be str",
            continue
        if not isinstance(vols, int | None):
            warnings += f"ReporterEntry {key}: vols must be int or None",
            continue
        if not isinstance(er_vol, list) or not all(isinstance (item, int | None) for item in er_vol):
            warnings += f"ReporterEntry {key}: er_vol must be list of int or None values only",
            continue
        if not isinstance(series, list) or not all(isinstance (item, str | None) for item in series):
            warnings += f"ReporterEntry {key}: series must be list of str or None values only",
            continue
        entries[key] = ReporterEntry(
            canonical_abbrev = canonical_abbrev,
            vols = vols,
            er_vol = tuple(er_vol),
            series = tuple(series)
        )

    return ReporterMap(entries=entries, warnings=warnings)


def load_config(data_path: Path) -> Config:
    
    abbrev_map = load_regex_map(data_path / ABBREV_MAP_FILENAME)
    spelling_variants = load_regex_map(data_path / SPELL_MAP_FILENAME)
    reporter_map = load_reporter_map(data_path / REPORTER_MAP_FILENAME)
    company_abbrev = load_regex_map(data_path / COMPANY_MAP_FILENAME)

    return Config(
        abbrev_map=abbrev_map,
        spelling_variants=spelling_variants,
        reporter_map=reporter_map,
        company_abbrev=company_abbrev
    )


