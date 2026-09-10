from sources.batch2_radancy_country_engine import collect_country_source

ASTRAZENECA_VERSION = "1.0"
LISTING_URL = "https://careers.astrazeneca.com/location/belgium-jobs/7684/2802361/2"

def collect_astrazeneca_jobs():
    return collect_country_source(
        "ASTRAZENECA",
        "AstraZeneca",
        LISTING_URL,
    )
