from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Iata = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())


Price = Annotated[Decimal, Field(ge=0)]
