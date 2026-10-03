import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Timestamped(OrmModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
