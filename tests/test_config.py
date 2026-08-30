import json

import pytest

from rollbook.config import ConfigError, load_config, load_regex_map, load_reporter_map


def test_load_regex_map_valid_entry(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps({r"\bBirm\.?\b": "Birmingham"}))

    result = load_regex_map(data_file)
    assert result.warnings == ()
    assert len(result.patterns) == 1


def test_load_regex_map_with_bad_regex(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps({r"\bBirm\.?\b": "Birmingham", r"\Birm\.?\b(": "Birmingham"}))

    result = load_regex_map(data_file)
    assert len(result.warnings) == 1
    assert len(result.patterns) == 1 


def test_load_regex_map_non_string(tmp_path): 
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps({r"\bBirm\.?\b": "Birmingham", r"\bLon\.?\b": 100}))

    result = load_regex_map(data_file)
    assert len(result.warnings) == 1
    assert len(result.patterns) == 1


def test_load_regex_map_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_regex_map(tmp_path / "notfile.json")


def test_load_reporter_map_valid_entry(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps(
        {"Ad & E": {"canonical_abbrev": "ad e", "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]}}
    ))
    result = load_reporter_map(data_file)

    assert result.warnings == ()
    assert len(result.entries) == 1


def test_load_reporter_map_wrong_canonical_abbrev(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps(
        {"Ad & E": {"canonical_abbrev": "ad e", "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]}, "Ad&E": {"canonical_abbrev": 4, "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]}}
    ))
    result = load_reporter_map(data_file)

    assert len(result.warnings) == 1
    assert len(result.entries) == 1


def test_load_reporter_map_wrong_vols(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps(
        {"Ad & E": {"canonical_abbrev": "ad e", "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]}, "Dears & Bell": { "canonical_abbrev": "dears & bell",  "vols": None, "er_vol": [169], "series": ["Crown."]},
        "D&B": { "canonical_abbrev": "dears & bell",  "vols": "None", "er_vol": [169], "series": ["Crown."]}} 
    ))
    result = load_reporter_map(data_file)

    assert len(result.warnings) == 1
    assert len(result.entries) == 2


def test_load_reporter_map_wrong_ervol(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps(
        {"Ad & E": {"canonical_abbrev": "ad e", "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]}, 
        "Dears & Bell": { "canonical_abbrev": "dears & bell",  "vols": None, "er_vol": [169], "series": ["Crown."]}, 
        "D&B": { "canonical_abbrev": "dears & bell",  "vols": None, "er_vol": [169, "string"], "series": ["Crown."]}} 
    ))
    
    result = load_reporter_map(data_file)

    assert len(result.warnings) == 1
    assert len(result.entries) == 2


def test_load_reporter_map_not_dict(tmp_path):
    data_file = tmp_path / "test.json"
    data_file.write_text(json.dumps(
        {"Ad & E": {"canonical_abbrev": "ad e", "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]},
        "Dears & Bell": "a plain string not a dict"} 
    ))
    
    result = load_reporter_map(data_file)

    assert len(result.warnings) == 1
    assert len(result.entries) == 1


def test_load_reporter_map_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_reporter_map(tmp_path / "notfile.json")


def test_load_config(tmp_path):
    abbrev_map = tmp_path / "abbrev_map.json"
    reporters = tmp_path / "reporters.json"
    spell = tmp_path / "spell.json"
    companies = tmp_path /  "companies.json"

    abbrev_map.write_text(json.dumps({r"\bBirm\.?\b": "Birmingham"}))

    reporters.write_text(json.dumps(
        {"Ad & E": {"canonical_abbrev": "ad e", "vols": 12, "er_vol": [110, 111, 112, 113], "series": ["K.B."]}}
    ))

    spell.write_text(json.dumps(
        {r"Salop": "shropshire"}
    ))

    companies.write_text(json.dumps(
        {r"\bSouth\s*York\s*Ry\.?\b": "South Yorkshire Railway Company"}
    ))

    Config = load_config(tmp_path)

    assert len(Config.abbrev_map.patterns) == 1
    assert Config.abbrev_map.warnings == ()
    assert len(Config.company_abbrev.patterns) == 1 
    assert Config.company_abbrev.warnings == ()
    assert len(Config.spelling_variants.patterns) == 1
    assert Config.spelling_variants.warnings == ()
    assert len(Config.reporter_map.entries) == 1
    assert Config.reporter_map.warnings == ()




