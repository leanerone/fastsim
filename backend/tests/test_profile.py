"""Profile loader validation tests."""
import pytest

from fastsim.core.profile import Profile, ProfileLoader
from tests.conftest import PROFILES_DIR


def test_load_etcher_profile():
    loader = ProfileLoader(PROFILES_DIR)
    data = loader.load("etcher-001.yaml")
    assert data["profile"]["mdln"] == "ETCH300"
    assert "1001" in data["status_variables"]
    assert data["connection"]["mode"] == "PASSIVE"
    assert data["connection"]["timeouts"]["t3"] == 45
    assert "START" in data["remote_commands"]
    assert data["behavior"]["on_remote_command"]["START"]["trigger_ceid"] == 6003


def test_reject_bad_mode():
    with pytest.raises(Exception):
        Profile.model_validate({"connection": {"mode": "SIDEWAYS"}})


def test_reject_bad_var_type():
    with pytest.raises(Exception):
        Profile.model_validate({"status_variables": {"1": {"name": "x", "type": "ZZ"}}})


def test_reject_bad_control_state():
    with pytest.raises(Exception):
        Profile.model_validate({"connection": {"initial_control_state": "MARS"}})


def test_int_keys_normalized():
    p = Profile.model_validate({
        "status_variables": {1001: {"name": "X", "type": "A"}},
        "alarms": {5001: {"name": "A1"}},
    })
    assert "1001" in p.status_variables
    assert p.status_variables["1001"].id == 1001


def test_validate_and_save_roundtrip(tmp_path):
    loader = ProfileLoader(tmp_path)
    text = (PROFILES_DIR / "etcher-001.yaml").read_text(encoding="utf-8")
    loader.save("copy.yaml", text)
    assert "copy.yaml" in loader.list_profiles()
    data = loader.load("copy.yaml")
    assert data["profile"]["model"] == "ETCH-300"


def test_missing_profile():
    loader = ProfileLoader(PROFILES_DIR)
    with pytest.raises(FileNotFoundError):
        loader.load("no-such-machine.yaml")
