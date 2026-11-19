"""Machine profile: Pydantic models + YAML loading (the GEM data dictionary)."""
from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class ProfileMeta(BaseModel):
    name: str = "Unnamed Tool"
    vendor: str = ""
    model: str = ""
    location: str = ""
    mdln: str = "FASTSIM"
    softrev: str = "1.0.0"


class Timeouts(BaseModel):
    t3: float = 45.0
    t5: float = 10.0
    t6: float = 5.0
    t7: float = 10.0
    t8: float = 5.0
    linktest: float = 30.0


class Connection(BaseModel):
    mode: str = "PASSIVE"          # PASSIVE (equipment) | ACTIVE (host)
    host: str = "127.0.0.1"
    port: int = 5000
    device_id: int = 0
    initial_control_state: str = "ONLINE_REMOTE"
    timeouts: Timeouts = Timeouts()

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        v = v.upper()
        if v not in ("ACTIVE", "PASSIVE"):
            raise ValueError("mode must be ACTIVE or PASSIVE")
        return v

    @field_validator("initial_control_state")
    @classmethod
    def _cst(cls, v: str) -> str:
        allowed = {"EQUIPMENT_OFFLINE", "ATTEMPT_ONLINE", "HOST_OFFLINE",
                   "ONLINE_LOCAL", "ONLINE_REMOTE", "ONLINE"}
        if v not in allowed:
            raise ValueError(f"initial_control_state must be one of {allowed}")
        return v


class VarDef(BaseModel):
    id: Optional[Any] = None        # original YAML key (int or str)
    name: str
    type: str = "A"                 # SECS-II kind
    unit: str = ""
    enum: Optional[List[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    default: Optional[Any] = None
    initial: Optional[Any] = None
    description: str = ""

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        allowed = {"L", "B", "BOOLEAN", "A", "J", "I1", "I2", "I4", "I8",
                   "F4", "F8", "U1", "U2", "U4", "U8"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v


class AlarmDef(BaseModel):
    id: Optional[Any] = None
    name: str
    text: str = ""
    category: int = 0
    ceid_on: Optional[Any] = None
    ceid_off: Optional[Any] = None


class EventDef(BaseModel):
    name: str = ""
    reports: List[Any] = []


class ReportDef(BaseModel):
    variables: List[Any] = []


class CommandParam(BaseModel):
    type: str = "A"
    required: bool = False
    description: str = ""


class CommandDef(BaseModel):
    description: str = ""
    params: Dict[str, CommandParam] = {}
    ceid: Optional[Any] = None


class Behavior(BaseModel):
    auto_establish: bool = True          # host: auto send S1F13 after select
    auto_reply_s1f13: bool = True        # equipment: auto accept CR
    online_mode: str = "ONLINE_REMOTE"
    on_remote_command: Dict[str, dict] = {}


class Profile(BaseModel):
    """Complete machine profile (validated)."""
    profile: ProfileMeta = ProfileMeta()
    connection: Connection = Connection()
    status_variables: Dict[str, VarDef] = {}
    data_variables: Dict[str, VarDef] = {}
    equipment_constants: Dict[str, VarDef] = {}
    alarms: Dict[str, AlarmDef] = {}
    collection_events: Dict[str, EventDef] = {}
    reports: Dict[str, ReportDef] = {}
    remote_commands: Dict[str, CommandDef] = {}
    behavior: Behavior = Behavior()

    model_config = {"protected_namespaces": ()}

    @field_validator("status_variables", "data_variables", "equipment_constants",
                     "alarms", "collection_events", "reports", "remote_commands",
                     mode="before")
    @classmethod
    def _stringify_keys(cls, v: Any) -> Any:
        """YAML parses `1001:` as int key; SECS ids may be int or str. Normalize
        dict keys to str while preserving the original id inside the model."""
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                if isinstance(val, dict):
                    val = dict(val)
                    val.setdefault("id", k)
                out[str(k)] = val
            return out
        return v


class ProfileLoader:
    def __init__(self, profiles_dir: pathlib.Path):
        self.profiles_dir = pathlib.Path(profiles_dir)

    def list_profiles(self) -> List[str]:
        if not self.profiles_dir.exists():
            return []
        return sorted(p.name for p in self.profiles_dir.glob("*.yaml")
                      if p.name != "template.yaml")

    def load(self, name: str) -> dict:
        """Load & validate profile; returns plain dict for the engine.

        Key normalization: YAML keys may be written as ints or strings; we
        keep them as-is (engine accepts both) but ensure str/int consistency.
        """
        path = self.profiles_dir / name
        if not path.exists() and not name.endswith(".yaml"):
            path = self.profiles_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"profile not found: {name}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prof = Profile.model_validate(raw)
        data = prof.model_dump()
        return data

    def validate_text(self, text: str) -> Profile:
        raw = yaml.safe_load(text) or {}
        return Profile.model_validate(raw)

    def save(self, name: str, text: str) -> None:
        self.validate_text(text)
        path = self.profiles_dir / name
        path.write_text(text, encoding="utf-8")


def load_profile_dict(path: str | pathlib.Path) -> dict:
    """Convenience for tests/scripts: load raw profile file -> validated dict."""
    return ProfileLoader(pathlib.Path(path).parent).load(pathlib.Path(path).name)
