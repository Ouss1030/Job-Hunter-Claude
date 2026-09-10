from sources.batch2_radancy_country_engine import collect_country_source

AMGEN_VERSION = "1.0"
LISTING_URL = "https://careers.amgen.com/en/search-jobs?acm=ALL&alrpm=2802361"

def collect_amgen_jobs():
    return collect_country_source(
        "AMGEN",
        "Amgen",
        LISTING_URL,
    )
