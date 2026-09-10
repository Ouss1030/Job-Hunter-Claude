from sources.batch2_employer_engine import EmployerConfig, collect_employer

SOLVAY_VERSION = "1.0"
CONFIG = EmployerConfig(
    key="SOLVAY",
    label="Solvay",
    company="Solvay",
    kind="SUCCESSFACTORS",
    base_url="https://careers.solvay.com",
    listing_url="https://careers.solvay.com/search/?q=",
    job_href_re=r"/job/",
    max_pages=8,
    page_size=20,
)

def collect_solvay_jobs():
    return collect_employer(CONFIG)
