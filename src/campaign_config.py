from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class CampaignConfigValidationError(ValueError):
    def __init__(self, field: str):
        self.field = field
        super().__init__(field)


class CampaignConfigModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    knowledge_bases: list[str] = Field(default_factory=list)
    target_personas: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    tone: str = "professional"
    email_goal: str = "book a 20-minute discovery call"
    max_email_words: int = Field(default=150, ge=50, le=400)
    max_linkedin_chars: int = 280
    key_pain_points: list[str] = Field(default_factory=list)

    @field_validator("tone")
    @classmethod
    def validate_tone(cls, value: str) -> str:
        if value not in {"professional", "conversational"}:
            raise ValueError("tone")
        return value

    @field_validator("knowledge_bases")
    @classmethod
    def validate_knowledge_bases(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError("knowledge_bases")
        return value


def validate_campaign_config(config: dict | None) -> dict:
    try:
        return CampaignConfigModel(**(config or {})).model_dump()
    except ValidationError as exc:
        field = "config"
        errors = exc.errors()
        if errors:
            loc = errors[0].get("loc") or ()
            if loc:
                field = str(loc[-1])
        raise CampaignConfigValidationError(field) from exc
