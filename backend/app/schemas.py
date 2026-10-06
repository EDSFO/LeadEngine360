from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class InvitationIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|manager|analyst|sdr|closer)$")


class AcceptInvitationIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class RoleUpdateIn(BaseModel):
    role: str = Field(pattern="^(admin|manager|analyst|sdr|closer)$")


class OfferIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    category: str = Field(default="software", pattern="^(software|service|other)$")
    description: str = Field(min_length=10)
    problem_solved: str | None = None
    differentiators: str | None = None
    target_customer_hint: str | None = None
    restrictions: str | None = None


class OnboardingIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    website: str | None = None
    company_description: str | None = None
    sales_regions: str | None = None
    offers: list[OfferIn] = Field(min_length=1, max_length=5)


class OnboardingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    company_id: str
    company_name: str
    offers: list[dict]


class ProfileOut(BaseModel):
    offer_id: str
    generated_with: str
    profile: dict
    evidence: list[dict]


class IcpUpdateIn(BaseModel):
    profile: dict
    status: str = Field(default="draft", pattern="^(draft|approved)$")


class SignalIn(BaseModel):
    signal_type: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(min_length=3, max_length=12000)
    source_url: str | None = Field(default=None, max_length=1000)
    evidence: str | None = Field(default=None, max_length=12000)
    occurred_at: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    strength: int = Field(default=3, ge=1, le=5)


class ActivityIn(BaseModel):
    activity_type: str = Field(pattern="^(contacted|replied|meeting|opportunity|won|lost)$")
    channel: str | None = Field(default=None, max_length=40)
    outcome: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=12000)
    occurred_at: str | None = None
