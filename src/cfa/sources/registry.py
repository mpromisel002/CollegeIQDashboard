"""Source registry: pointers (UnitIDs and document URLs) only, never college data.

Loaded from GitHub at runtime so broken CDS links can be fixed without a rebuild; the copy
bundled with the app is the fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from cfa import config
from cfa.sources.http import HttpClient

log = logging.getLogger(__name__)


class CdsDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: str = Field(pattern=r"^\d{4}-\d{4}$")
    url: str
    format: Literal["pdf", "xlsx"]

    @field_validator("url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("CDS URL must be https")
        return v


class Links(BaseModel):
    model_config = ConfigDict(extra="forbid")
    niche: str | None = None
    petersons: str | None = None
    bigfuture: str | None = None
    collegetransitions_greek: str | None = None


class School(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unitid: int = Field(gt=0)
    name: str
    cds: list[CdsDoc] = Field(default_factory=list)
    links: Links = Field(default_factory=Links)

    @property
    def latest_cds(self) -> CdsDoc | None:
        return max(self.cds, key=lambda d: d.year) if self.cds else None


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    schools: list[School]

    @model_validator(mode="after")
    def _unique(self) -> Registry:
        ids = [s.unitid for s in self.schools]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate unitid in registry")
        return self

    def get(self, unitid: int) -> School | None:
        return next((s for s in self.schools if s.unitid == unitid), None)


@dataclass
class RegistryLoad:
    registry: Registry
    origin: Literal["remote", "bundled", "empty"]
    warning: str | None = None


def parse_registry(text: str | bytes) -> Registry:
    data = yaml.safe_load(text)
    return Registry.model_validate(data)


def load_bundled(path: Path | None = None) -> Registry:
    path = path or config.bundled_path("registry/schools.yaml")
    return parse_registry(path.read_text(encoding="utf-8"))


async def load_registry(
    http: HttpClient, remote_url: str = config.REGISTRY_REMOTE_URL, bundled: Path | None = None
) -> RegistryLoad:
    warning: str | None = None
    res = await http.get(remote_url)
    if res.ok:
        try:
            return RegistryLoad(parse_registry(res.content), "remote")
        except (yaml.YAMLError, ValidationError, TypeError) as exc:
            log.warning("Remote registry rejected: %s", type(exc).__name__)
            warning = "The online school list is malformed; using the list bundled with the app."
    else:
        warning = "Could not download the latest school list; using the list bundled with the app."
    try:
        return RegistryLoad(load_bundled(bundled), "bundled", warning)
    except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
        log.error("Bundled registry unusable: %s", type(exc).__name__)
        return RegistryLoad(
            Registry(schema_version=1, schools=[]), "empty", "No usable school list is available."
        )
