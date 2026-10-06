"""Onboarding checklist + sample-data mode.

GET    /onboarding    -> checklist of the workspace's own setup steps (sample rows excluded)
POST   /sample-data   -> load a demo candle brand into the workspace (admin; once)
DELETE /sample-data   -> remove everything sample mode created (admin)
"""

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.deps import DB, Ctx, OrgId
from app.services import audit, onboarding, sample_data


class StepOut(BaseModel):
    key: str
    title: str
    hint: str
    href: str
    done: bool


class OnboardingOut(BaseModel):
    steps: list[StepOut]
    done: int
    total: int
    complete: bool
    sample_data: bool


class SampleLoaded(BaseModel):
    loaded: bool


class SampleRemoved(BaseModel):
    removed_products: int


router = APIRouter(tags=["onboarding"])


@router.get("/onboarding", response_model=OnboardingOut)
def get_onboarding(db: DB, org_id: OrgId) -> OnboardingOut:
    steps, has_sample = onboarding.status(db, org_id)
    done = sum(s.done for s in steps)
    return OnboardingOut(
        steps=[StepOut(**s.__dict__) for s in steps],
        done=done,
        total=len(steps),
        complete=done == len(steps),
        sample_data=has_sample,
    )


@router.post("/sample-data", response_model=SampleLoaded, status_code=status.HTTP_201_CREATED)
def load_sample_data(db: DB, ctx: Ctx) -> SampleLoaded:
    ctx.require("admin")
    loaded = sample_data.load(db, ctx.org_id)
    if loaded:
        audit.record(
            db, ctx, action="sample_data.load", entity="organization", entity_id=ctx.org_id
        )
    db.commit()
    return SampleLoaded(loaded=loaded)


@router.delete("/sample-data", response_model=SampleRemoved)
def remove_sample_data(db: DB, ctx: Ctx) -> SampleRemoved:
    ctx.require("admin")
    n = sample_data.remove(db, ctx.org_id)
    audit.record(
        db,
        ctx,
        action="sample_data.remove",
        entity="organization",
        entity_id=ctx.org_id,
        after={"removed_products": n},
    )
    db.commit()
    return SampleRemoved(removed_products=n)
