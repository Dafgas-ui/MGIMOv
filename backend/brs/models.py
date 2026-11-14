from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Key = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Day = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
Points = Annotated[int, Field(ge=0, le=100)]


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Category(Strict):
    code: Key
    title: Label
    maximum: Points
    admission_min: Points | None = None


class Event(Category):
    category_code: Key
    attempt_limit: int = Field(ge=1, le=10)
    retake_policy: Literal["none", "latest", "highest"]
    retake_until: Day | None = None


class Threshold(Strict):
    minimum: Points
    outcome: Literal["2", "3", "4", "5", "fail", "pass"]


class Plan(Strict):
    curriculum_id: Key
    source: str = Field(min_length=1, max_length=500)
    approved_on: Day
    rounding: Literal["exact", "floor", "half_up"]
    admission_min: Points
    categories: list[Category] = Field(min_length=1, max_length=20)
    events: list[Event] = Field(min_length=1, max_length=100)
    scale: list[Threshold] = Field(min_length=1, max_length=4)


class Offering(Strict):
    plan_id: Key
    group_id: Key


class Teacher(Strict):
    staff_id: Key
    teacher_id: Key
    lesson_id: Key


class Grant(Strict):
    staff_id: Key
    lesson_id: Key
    lesson_version: int = Field(ge=1)
    expires_at: int = Field(gt=0, le=2**63-1)
    can_confirm_final: bool = False
    event_code: Key | None = None


class Enrollment(Strict):
    student_id: Key
    starts_on: Day


class Mapping(Strict):
    old_event: Key
    new_event: Key


class Transfer(Strict):
    target_offering_id: Key
    starts_on: Day
    reason: Label
    mapping: list[Mapping] = Field(default_factory=list, max_length=100)


AttemptNumber = Annotated[int, Field(ge=1, le=10)]
VersionNumber = Annotated[int, Field(ge=0, le=2**63-1)]


class ResultDraft(Strict):
    points: Points
    expected_draft_version: VersionNumber


class ResultCommand(Strict):
    request_key: Key
    expected_result_version: VersionNumber


class PublishResult(ResultCommand):
    expected_draft_version: int = Field(ge=1, le=2**63-1)


class CorrectResult(ResultCommand):
    points: Points
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
