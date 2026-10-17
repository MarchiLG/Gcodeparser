import json

import pytest

from gcodepen.profiles import ProfileStore, default_path


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path / "cfg" / "profiles.json")   # a pasta ainda não existe


def test_empty_store(store):
    assert store.load() == {"autosave": None, "profiles": {}}


def test_autosave_roundtrip_and_persistence(store):
    cfg = {"feed": "600", "quadrant": 4, "zero": True, "pen": "servo"}
    store.set_autosave(cfg)
    assert ProfileStore(store.path).load()["autosave"] == cfg   # outra instância = reabrir o programa


def test_named_profiles_save_overwrite_delete(store):
    assert store.save("  Plotter   A4 ", {"feed": "400"}) == "Plotter A4"
    store.save("Plotter A4", {"feed": "800"})
    store.save("Outro", {"pen": "z"})
    p = store.load()["profiles"]
    assert p["Plotter A4"] == {"feed": "800"} and set(p) == {"Plotter A4", "Outro"}
    store.delete("Outro")
    assert set(store.load()["profiles"]) == {"Plotter A4"}
    with pytest.raises(KeyError):
        store.delete("Outro")


def test_autosave_does_not_touch_profiles(store):
    store.save("A", {"x": 1})
    store.set_autosave({"y": 2})
    assert store.load()["profiles"] == {"A": {"x": 1}}


@pytest.mark.parametrize("bad", [None, [], "x", {"a": [1]}, {"a": {"b": 1}}, {"a": "x" * 201}, {"": 1}, {"k" * 41: 1}])
def test_rejects_bad_settings(store, bad):
    with pytest.raises(ValueError):
        store.set_autosave(bad)
    assert not store.path.exists()


@pytest.mark.parametrize("name", ["", "   ", None, "n" * 61])
def test_rejects_bad_names(store, name):
    with pytest.raises(ValueError):
        store.save(name, {})


def test_corrupt_file_is_tolerated_and_replaced(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{ isto não é json")
    assert store.load() == {"autosave": None, "profiles": {}}
    store.save("A", {"x": 1})
    assert json.loads(store.path.read_text())["profiles"] == {"A": {"x": 1}}
    assert not store.path.with_suffix(".tmp").exists()


def test_config_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GCODEPEN_CONFIG", str(tmp_path / "p.json"))
    assert default_path() == tmp_path / "p.json"
    monkeypatch.delenv("GCODEPEN_CONFIG")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_path() == tmp_path / "gcodepen" / "profiles.json"


def test_server_travel_feed_and_rates():
    from gcodepen.server import build_job
    res = build_job({"text": "Oi", "travel_feed": "1500", "feed": "300", "rate_x": "1000", "rate_y": "1000"})
    assert "G1 X" in res.gcode and " F1500" in res.gcode
    assert not any("acima do $110" in w for w in res.warnings)
    res = build_job({"text": "Oi", "travel_feed": "", "feed": "800"})
    assert "G0 X" in res.gcode and any("acima do $110" in w for w in res.warnings)
