from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Signal = Literal["eeg", "ecg", "eog", "imu", "video_features"]
Category = Literal["classical_ml", "deep_learning", "hybrid"]
EventType = Literal["view", "save", "select", "rating"]
Positive = Annotated[float, Field(ge=0.001, le=1_000_000, allow_inf_nan=False)]
ObjectIdString = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{24}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DeviceProfile(StrictModel):
    signal: Signal
    memory_budget_mb: Positive
    max_latency_ms: Positive
    reference_device: str = Field(min_length=1, max_length=100)


class Register(StrictModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("password", mode="before")
    @classmethod
    def keep_password(cls, value):
        # Password whitespace is significant, unlike display-name whitespace.
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Leading/trailing password whitespace is not supported")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class ProfileUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=80)
    device: DeviceProfile | None = None


class Requirements(StrictModel):
    memory_mb: Positive
    latency_ms: Positive
    reference_device: str = Field(min_length=1, max_length=100)


class Evaluation(StrictModel):
    f1: float = Field(ge=0, le=1, allow_inf_nan=False)
    dataset: str = Field(min_length=1, max_length=100)
    protocol: str = Field(min_length=1, max_length=200)


class CatalogModel(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    version: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=4000)
    category: Category
    signals: list[Signal] = Field(min_length=1, max_length=5)
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=15
    )
    requirements: Requirements
    evaluation: Evaluation
    synthetic: bool = True

    @field_validator("signals", "tags")
    @classmethod
    def unique_values(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate values are not allowed")
        return value


class Interaction(StrictModel):
    model_id: ObjectIdString
    type: EventType
    rating: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None
    request_id: UUID = Field(default_factory=uuid4)

    @model_validator(mode="after")
    def rating_matches_type(self):
        if (self.type == "rating") != (self.rating is not None):
            raise ValueError("rating must be supplied only for a rating event")
        return self
