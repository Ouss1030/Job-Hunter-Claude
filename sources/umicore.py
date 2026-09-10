from sources.batch2_employer_engine import EmployerConfig, collect_employer

UMICORE_VERSION = "1.0"
CONFIG = EmployerConfig(
    key="UMICORE",
    label="Umicore",
    company="Umicore",
    kind="UMICORE",
    base_url="https://www.umicore.com",
    listing_url="https://www.umicore.com/en/careers/job-finder/",
    job_href_re=r"/en/careers/job-finder/\d+-",
    max_pages=20,
    page_size=20,
)

def collect_umicore_jobs():
    # IMPORTANT: Umicore's ?locationsearch=Belgium was proven untrusted.
    # Every target candidate is therefore validated from the DETAIL location.
    return collect_employer(CONFIG)
