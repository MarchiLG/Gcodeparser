"""Perfis de configuração da UI: o estado automático (última sessão) e perfis nomeados.

Guardados em JSON no servidor (e não no localStorage) para sobreviver a mudança de porta/navegador.
Arquivo: $GCODEPEN_CONFIG, senão $XDG_CONFIG_HOME/gcodepen/profiles.json, senão ~/.config/gcodepen/profiles.json.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

MAX_PROFILES = 100
MAX_KEYS = 80
MAX_NAME = 60


def default_path() -> Path:
    if os.environ.get("GCODEPEN_CONFIG"):
        return Path(os.environ["GCODEPEN_CONFIG"])
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "gcodepen" / "profiles.json"


def clean_settings(data) -> dict:
    """Só aceita {str: str|int|float|bool} pequeno — vem do navegador, então não se confia no formato."""
    if not isinstance(data, dict):
        raise ValueError("configurações inválidas")
    if len(data) > MAX_KEYS:
        raise ValueError("configurações demais")
    out = {}
    for k, v in data.items():
        if not isinstance(k, str) or not 0 < len(k) <= 40:
            raise ValueError("chave inválida")
        if isinstance(v, str):
            if len(v) > 200:
                raise ValueError(f"valor longo demais em '{k}'")
        elif not isinstance(v, (bool, int, float)):
            raise ValueError(f"tipo inválido em '{k}'")
        out[k] = v
    return out


def clean_name(name) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("dê um nome ao perfil")
    if len(name) > MAX_NAME:
        raise ValueError(f"nome longo demais (máx. {MAX_NAME})")
    return name


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_path()
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # ausente ou corrompido: recomeça vazio
            data = {}
        if not isinstance(data, dict):
            data = {}
        profiles = data.get("profiles")
        autosave = data.get("autosave")
        return {"autosave": autosave if isinstance(autosave, dict) else None,
                "profiles": profiles if isinstance(profiles, dict) else {}}

    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)   # atômico: nunca deixa um JSON pela metade

    def load(self) -> dict:
        with self._lock:
            return self._read()

    def set_autosave(self, settings) -> None:
        settings = clean_settings(settings)
        with self._lock:
            data = self._read()
            data["autosave"] = settings
            self._write(data)

    def save(self, name, settings) -> str:
        name, settings = clean_name(name), clean_settings(settings)
        with self._lock:
            data = self._read()
            if name not in data["profiles"] and len(data["profiles"]) >= MAX_PROFILES:
                raise ValueError("limite de perfis atingido")
            data["profiles"][name] = settings
            self._write(data)
        return name

    def delete(self, name) -> None:
        with self._lock:
            data = self._read()
            if data["profiles"].pop(str(name), None) is None:
                raise KeyError("perfil inexistente")
            self._write(data)
