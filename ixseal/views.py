"""고객 화면 뷰 모델. 실제 고객 화면과 관리 화면 미리보기가 같은 함수를 거쳐 같은 Jinja 템플릿으로 그려진다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .files import extension, human_size
from .render import remaining_text
from .schema import EXPIRY_HOURS, PreviewIn

POLICY_CHIP = {"unlimited": "기한 내 자유 열람", "until_confirmed": "확인 후 폐기", "one_time": "1회 열람"}
POLICY_ICON = {"unlimited": "i-clock", "until_confirmed": "i-check", "one_time": "i-flame"}

EMPTY_TEXT = {"form": "아직 입력하지 않음", "tpl": "등록 시 입력"}
EMPTY_FILE = {"form": "파일 선택 전", "tpl": "등록 시 첨부"}


@dataclass
class FileView:
    id: str
    name: str
    size: int
    size_text: str
    badge: str


@dataclass
class FieldView:
    label: str
    type: str
    value: str
    empty: bool
    is_link: bool = False
    file: FileView | None = None


@dataclass
class InstanceView:
    no: int
    title_value: str | None
    fields: list[FieldView]


@dataclass
class SectionView:
    title: str
    repeat: bool
    unit: str
    instances: list[InstanceView]
    notices: list[dict]


@dataclass
class CustomerView:
    mode: str  # real | form | tpl
    customer: str
    title: str
    owner: str
    policy: str
    expires_at: datetime
    remaining: str
    sections: list[SectionView] = field(default_factory=list)
    attachments: list[FileView] = field(default_factory=list)

    @property
    def policy_chip(self) -> str:
        return POLICY_CHIP[self.policy]

    @property
    def policy_icon(self) -> str:
        return POLICY_ICON[self.policy]

    @property
    def preview(self) -> bool:
        return self.mode != "real"

    @property
    def has_files(self) -> bool:
        return bool(self.attachments) or any(
            f.file for s in self.sections for inst in s.instances for f in inst.fields
        )

    def empty_text(self, f: FieldView) -> str:
        return (EMPTY_FILE if f.type == "file" else EMPTY_TEXT).get(self.mode, "")


def _file_view(f: dict) -> FileView:
    ext = extension(f["name"]).upper()[:4] or "FILE"
    return FileView(id=f["id"], name=f["name"], size=f.get("size", 0), size_text=human_size(f.get("size", 0)), badge=ext)


def build_sections(sections: list[dict], files: list[dict], mode: str) -> tuple[list[SectionView], list[FileView]]:
    by_id = {f["id"]: _file_view(f) for f in files}
    used: set[str] = set()
    out: list[SectionView] = []
    for s in sections:
        instances: list[InstanceView] = []
        for i, inst in enumerate(s.get("instances", [])):
            fields: list[FieldView] = []
            for f in inst:
                ftype = f.get("type", "text")
                if ftype == "file":
                    fv = by_id.get(f.get("file_id") or "")
                    if fv:
                        used.add(fv.id)
                    fields.append(FieldView(f.get("label", ""), "file", fv.name if fv else "", fv is None, file=fv))
                    continue
                value = f.get("value", "") or ""
                is_link = ftype == "url" and value.startswith(("https://", "http://"))
                fields.append(FieldView(f.get("label", ""), ftype, value, not value.strip(), is_link))
            if mode == "real":
                fields = [f for f in fields if not f.empty]
            title_value = None
            if s.get("repeat") and fields and fields[0].type == "text" and not fields[0].empty:
                title_value, fields = fields[0].value, fields[1:]
            instances.append(InstanceView(i + 1, title_value, fields))
        notices = [n for n in s.get("notices", []) if (n.get("text") or "").strip()]
        if mode == "real" and not notices and not any(inst.fields or inst.title_value for inst in instances):
            continue
        out.append(
            SectionView(
                title=s.get("title") or "계정 정보",
                repeat=bool(s.get("repeat")),
                unit=s.get("unit") or "항목",
                instances=instances,
                notices=notices,
            )
        )
    attachments = [fv for fid, fv in by_id.items() if fid not in used]
    return out, attachments


def real_view(row: dict, payload: dict | None) -> CustomerView:
    v = CustomerView(
        mode="real",
        customer=row["customer_name"],
        title=row["title"],
        owner=row["owner_name"],
        policy=row["policy"],
        expires_at=row["expires_at"],
        remaining=remaining_text(row["expires_at"]),
    )
    if payload is not None:
        v.sections, v.attachments = build_sections(payload.get("sections", []), payload.get("files", []), "real")
    return v


def preview_view(p: PreviewIn) -> CustomerView:
    expires = datetime.now(timezone.utc) + timedelta(hours=EXPIRY_HOURS[p.meta.expiry])
    files = [{"id": f"p{i}", "name": f.name or "file", "size": f.size} for i, f in enumerate(p.files)]
    sections = []
    for s in p.sections:
        d = s.model_dump()
        for inst_in, inst_out in zip(s.instances, d["instances"]):
            for f_in, f_out in zip(inst_in, inst_out):
                if f_in.type == "file" and f_in.file_index is not None and f_in.file_index < len(files):
                    f_out["file_id"] = f"p{f_in.file_index}"
        sections.append(d)
    v = CustomerView(
        mode=p.mode,
        customer=p.meta.customer,
        title=p.meta.title,
        owner=p.meta.owner,
        policy=p.meta.policy,
        expires_at=expires,
        remaining=remaining_text(expires),
    )
    v.sections, v.attachments = build_sections(sections, files, p.mode)
    return v


MAIL_POLICY_LINE = {
    "unlimited": "· 기한 안에는 여러 번 열람할 수 있습니다.",
    "until_confirmed": "· 확인을 마치신 뒤 [확인 완료]를 누르면 즉시 폐기됩니다.",
    "one_time": "· 한 번만 열람할 수 있으니, 옮겨 적을 준비가 되었을 때 열어 주세요.",
}


def mail_text(*, customer: str, owner: str, title: str, link: str, deadline: str, policy: str, helpdesk: str) -> str:
    return (
        f"안녕하세요, {customer} 담당자님. IXcloud {owner}입니다.\n\n"
        f"요청하신 건의 계정정보를 아래 링크로 전달드립니다.\n"
        f"보안을 위해 계정정보는 메일에 직접 적지 않았습니다.\n\n"
        f"■ {title}\n"
        f"▶ {link}\n\n"
        f"· 열람 기한: {deadline}까지\n"
        f"{MAIL_POLICY_LINE[policy]}\n\n"
        f"문의사항은 Cloud 헬프데스크({helpdesk})로 보내 주세요.\n"
        f"감사합니다."
    )
