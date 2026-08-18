from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class JobOffer:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    description: str
    url: str

    date_published: Optional[str] = None
    contract_type: Optional[str] = None
    language: Optional[str] = None
    salary: Optional[str] = None

    date_collected: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )