from typing import List, Optional, Dict, Any
import re
from pydantic import BaseModel, field_validator, ConfigDict

class Virksomhed(BaseModel):

    cvr: int
    pNummer: int
    virksomhedsnavn: str

    @field_validator('cvr', 'pNummer')
    @classmethod
    def validate_positive(cls, v, info):
        if v <= 0:
            raise ValueError(f'{info.field_name} must be a positive number')
        return v
    
    @field_validator('virksomhedsnavn')
    @classmethod
    def validate_strings(cls, v, info):
        if v is None:
            raise ValueError(f'{info.field_name} must not be None')
        if not isinstance(v, str):
            raise ValueError(f'{info.field_name} must be a string')
        if not v.strip():
            raise ValueError(f'{info.field_name} must not be empty')
        return v

    