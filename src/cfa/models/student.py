"""Student profile entered by the advisor. Saved/loaded as JSON wherever the advisor chooses."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GreekDirection(StrEnum):
    WANTS = "wants"
    NEUTRAL = "neutral"
    AVOIDS = "avoids"


class Setting(StrEnum):
    ANY = "Any"
    CITY = "City"
    SUBURB = "Suburb"
    TOWN = "Town"
    RURAL = "Rural"


class SizePref(StrEnum):
    ANY = "Any"
    SMALL = "<5k"
    MEDIUM = "5-15k"
    LARGE = "15-30k"
    HUGE = ">30k"


class Athletics(StrEnum):
    ANY = "Any"
    NCAA = "NCAA"
    NAIA = "NAIA"


class StudentProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    gpa_unweighted: float | None = Field(default=None, ge=0.0, le=4.0)
    gpa_weighted: float | None = Field(default=None, ge=0.0, le=6.0)
    sat_ebrw: int | None = Field(default=None, ge=200, le=800)
    sat_math: int | None = Field(default=None, ge=200, le=800)
    act: int | None = Field(default=None, ge=1, le=36)
    submits_tests: bool = True
    intended_major: str = ""
    preferred_states: list[str] = Field(default_factory=list)
    size_pref: SizePref = SizePref.ANY
    size_importance: int = Field(default=0, ge=0, le=3)
    setting_pref: Setting = Setting.ANY
    setting_importance: int = Field(default=0, ge=0, le=3)
    greek_importance: int = Field(default=0, ge=0, le=3)
    greek_direction: GreekDirection = GreekDirection.NEUTRAL
    housing_importance: int = Field(default=0, ge=0, le=3)
    athletics_pref: Athletics = Athletics.ANY
    athletics_importance: int = Field(default=0, ge=0, le=3)
    region_importance: int = Field(default=0, ge=0, le=3)
    study_abroad_importance: int = Field(default=0, ge=0, le=3)
    ed_willing: bool = False
    ea_willing: bool = False
    notes: str = ""

    @field_validator("preferred_states", mode="before")
    @classmethod
    def _norm_states(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v = v.replace(";", ",").split(",")
        if not isinstance(v, list):
            return []
        return [str(s).strip().upper() for s in v if str(s).strip()]

    @property
    def sat_total(self) -> int | None:
        if self.sat_ebrw is None or self.sat_math is None:
            return None
        return self.sat_ebrw + self.sat_math

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> StudentProfile:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
