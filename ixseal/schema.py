"""입력 검증 모델 (템플릿, 전달 등록, 미리보기).

주의: `Short(...)` 호출형 타입 때문에 `from __future__ import annotations`를 쓰지 않는다.
"""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

FieldType = Literal["text", "secret", "url", "multi", "file"]
Tone = Literal["info", "warn"]
Policy = Literal["unlimited", "until_confirmed", "one_time"]
ExpiryKey = Literal["1h", "6h", "24h", "3d", "7d"]

EXPIRY_HOURS: dict[str, int] = {"1h": 1, "6h": 6, "24h": 24, "3d": 72, "7d": 168}
EXPIRY_LABEL: dict[str, str] = {"1h": "1시간", "6h": "6시간", "24h": "24시간", "3d": "3일", "7d": "7일"}
POLICY_LABEL: dict[str, str] = {
    "unlimited": "기간 내 무제한",
    "until_confirmed": "확인 후 폐기",
    "one_time": "1회 열람 후 폐기",
}
TYPE_LABEL: dict[str, str] = {"text": "텍스트", "secret": "비밀(가림)", "url": "URL", "multi": "여러 줄", "file": "파일"}

MAX_SECTIONS = 10
MAX_FIELDS = 30
MAX_INSTANCES = 20
MAX_NOTICES = 5

# 앞뒤 공백을 자르는 문자열
Short = lambda n, m=0: Annotated[str, StringConstraints(strip_whitespace=True, max_length=n, min_length=m)]  # noqa: E731


class Notice(BaseModel):
    tone: Tone = "info"
    text: str = Field("", max_length=1000)


# ───────── 템플릿 ─────────
class TemplateField(BaseModel):
    label: Short(60) = ""
    type: FieldType = "text"
    value: str = Field("", max_length=2000)
    required: bool = False

    @model_validator(mode="after")
    def _no_secret_default(self):
        if self.type in ("secret", "file") and self.value:
            raise ValueError("비밀·파일 항목에는 기본값을 둘 수 없습니다")
        return self


class TemplateSection(BaseModel):
    title: Short(60) = ""
    repeat: bool = False
    unit: Short(20) = ""
    fields: list[TemplateField] = Field(default_factory=list, max_length=MAX_FIELDS)
    notices: list[Notice] = Field(default_factory=list, max_length=MAX_NOTICES)


class TemplateIn(BaseModel):
    name: Short(60, 1)
    description: Short(200) = ""
    default_title: Short(120) = ""
    default_expiry: ExpiryKey = "24h"
    default_policy: Policy = "until_confirmed"
    sections: list[TemplateSection] = Field(min_length=1, max_length=MAX_SECTIONS)
    updated_by: Short(40, 1)


# ───────── 전달 ─────────
class DeliveryField(BaseModel):
    label: Short(60) = ""
    type: FieldType = "text"
    value: str = Field("", max_length=10000)
    required: bool = False
    file_index: int | None = Field(None, ge=0)


class DeliverySection(BaseModel):
    title: Short(60) = ""
    repeat: bool = False
    unit: Short(20) = ""
    instances: list[list[DeliveryField]] = Field(min_length=1, max_length=MAX_INSTANCES)
    notices: list[Notice] = Field(default_factory=list, max_length=MAX_NOTICES)

    @field_validator("instances")
    @classmethod
    def _limit_fields(cls, v):
        for inst in v:
            if len(inst) > MAX_FIELDS:
                raise ValueError(f"한 묶음의 항목은 {MAX_FIELDS}개까지입니다")
        return v


class DeliveryIn(BaseModel):
    template_id: uuid.UUID | None = None
    customer: Short(80, 1)
    title: Short(120, 1)
    ticket: Short(60) = ""
    owner: Short(40, 1)
    expiry: ExpiryKey = "24h"
    policy: Policy = "until_confirmed"
    sections: list[DeliverySection] = Field(min_length=1, max_length=MAX_SECTIONS)


# ───────── 미리보기 (검증을 느슨하게) ─────────
class PreviewFile(BaseModel):
    name: str = Field("", max_length=255)
    size: int = Field(0, ge=0)


class PreviewMeta(BaseModel):
    customer: str = Field("", max_length=80)
    title: str = Field("", max_length=120)
    owner: str = Field("", max_length=40)
    expiry: ExpiryKey = "24h"
    policy: Policy = "until_confirmed"


class PreviewIn(BaseModel):
    view: Literal["landing", "reveal"] = "reveal"
    mode: Literal["form", "tpl"] = "form"
    meta: PreviewMeta = Field(default_factory=PreviewMeta)
    sections: list[DeliverySection] = Field(default_factory=list, max_length=MAX_SECTIONS)
    files: list[PreviewFile] = Field(default_factory=list, max_length=50)


class OwnerIn(BaseModel):
    owner: Short(40, 1)
