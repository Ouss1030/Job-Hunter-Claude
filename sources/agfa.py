from pathlib import Path
from sources.batch2_employer_engine import EmployerConfig, collect_employer

AGFA_VERSION = "1.0"
CONFIG = EmployerConfig(
    key="AGFA",
    label="Agfa",
    company="Agfa",
    kind="SUCCESSFACTORS",
    base_url="https://careers.agfa.com",
    listing_url="https://careers.agfa.com/search/?q=&locationsearch=Belgium",
    job_href_re=r"/(?:HealthCare/)?job/",
    max_pages=8,
    page_size=20,
)

def collect_agfa_jobs():
    return collect_employer(CONFIG)
