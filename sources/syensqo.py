from sources.batch2_employer_engine import EmployerConfig, collect_employer

SYENSQO_VERSION = "1.0"
CONFIG = EmployerConfig(
    key="SYENSQO",
    label="Syensqo",
    company="Syensqo",
    kind="SUCCESSFACTORS",
    base_url="https://careers.syensqo.com",
    listing_url="https://careers.syensqo.com/search/?q=",
    job_href_re=r"/job/",
    max_pages=10,
    page_size=20,
)

def collect_syensqo_jobs():
    return collect_employer(CONFIG)
