"""
JOB HUNTER BELGIUM
ACTIRIS - TEST DE PROVENANCE V1

OBJECTIF
========

Déterminer ce que représentent réellement les offres
retournées par le moteur public Actiris.

On compare les mêmes recherches avec :

1. aucun filtre de provenance
2. Offres Actiris uniquement
3. VDAB / FOREM uniquement
4. Partenaires / autres offres uniquement
5. Handicap uniquement

On compare ensuite les références Actiris afin de savoir
si une offre récupérée via Actiris vient réellement :

- d'Actiris
- de VDAB / FOREM
- d'un partenaire
- du canal Handicap
- ou d'une catégorie non identifiée

AUCUNE donnée n'est enregistrée en SQLite.
AUCUN fichier existant n'est modifié.
"""


import time
from collections import defaultdict

from sources.actiris import (
    build_search_payload,
    request_actiris_api,
)


# ============================================================
# CONFIGURATION
# ============================================================

SEARCH_TERMS = [
    "data analyst",
    "technicien de laboratoire",
    "contrôle qualité",
]


PAGE_SIZE = 50

MAX_RESULTS_PER_SEARCH = 300

DELAY_BETWEEN_PAGES = 0.10


# ============================================================
# OFFRES QUE NOUS AVONS DÉJÀ REPÉRÉES
# ============================================================

WITNESS_REFERENCES = {

    "5905785":
        "Technicien·ne Chimiste de Laboratoire – Contrôle Qualité",

    "5903642":
        "Technicien de laboratoire QC",

    "5906598":
        "Technicien laboratoire HPLC",

    "5916750":
        "BI Analyst-Developer",

    "5916757":
        "BI Analyst-Developer",

    "5921256":
        "Data Engineer - Microsoft Fabric / Azure",

    "5920484":
        "Data Engineer Health Sector",

    "5909638":
        "Data Quality Analyst",
}


# ============================================================
# MODES DE PROVENANCE
# ============================================================

PROVENANCE_MODES = {

    "ALL": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            False,
    },


    "ACTIRIS": {
        "isOffreActiris":
            True,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            False,
    },


    "VDAB_FOREM": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            True,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            False,
    },


    "PARTNER": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            True,

        "isOffreHandicap":
            False,
    },


    "HANDICAP": {
        "isOffreActiris":
            False,

        "isOffreVdabForem":
            False,

        "isOfferPartner":
            False,

        "isOffreHandicap":
            True,
    },
}


# ============================================================
# CONSTRUCTION PAYLOAD
# ============================================================

def build_provenance_payload(
    keyword,
    page,
    provenance_mode
):

    payload = build_search_payload(

        keyword=
            keyword,

        page=
            page,

        page_size=
            PAGE_SIZE,
    )


    filters = (
        payload[
            "offreFilter"
        ]
    )


    provenance_config = (
        PROVENANCE_MODES[
            provenance_mode
        ]
    )


    for key, value in (
        provenance_config.items()
    ):

        filters[
            key
        ] = value


    return payload


# ============================================================
# RECHERCHE PAGINÉE
# ============================================================

def search_with_provenance(
    keyword,
    provenance_mode
):

    unique_jobs = {}

    total_reported = 0

    page = 1


    while True:

        payload = (
            build_provenance_payload(
                keyword=
                    keyword,

                page=
                    page,

                provenance_mode=
                    provenance_mode,
            )
        )


        try:

            data = request_actiris_api(
                payload
            )


        except Exception as error:

            print(
                f"      ❌ Erreur API : {error}"
            )

            break


        total_reported = int(
            data.get(
                "total",
                0
            )
            or 0
        )


        items = (
            data.get(
                "items",
                []
            )
            or []
        )


        if not items:

            break


        for item in items:

            reference = str(
                item.get(
                    "reference",
                    ""
                )
                or ""
            ).strip()


            if not reference:

                continue


            unique_jobs[
                reference
            ] = item


        if (
            len(
                unique_jobs
            )
            >=
            min(
                total_reported,
                MAX_RESULTS_PER_SEARCH
            )
        ):

            break


        if len(
            items
        ) < PAGE_SIZE:

            break


        page += 1


        time.sleep(
            DELAY_BETWEEN_PAGES
        )


    return {

        "total":
            total_reported,

        "jobs":
            unique_jobs,
    }


# ============================================================
# TITRE
# ============================================================

def get_title(
    job
):

    if not job:

        return ""


    return (
        job.get(
            "titreFr"
        )
        or
        job.get(
            "titreNl"
        )
        or
        ""
    )


# ============================================================
# ENTREPRISE
# ============================================================

def get_company(
    job
):

    if not job:

        return ""


    employer = (
        job.get(
            "employeur"
        )
        or {}
    )


    return (
        employer.get(
            "nomFr"
        )
        or
        employer.get(
            "nomNl"
        )
        or
        ""
    )


# ============================================================
# LIEU
# ============================================================

def get_location(
    job
):

    if not job:

        return ""


    return (
        job.get(
            "communeFr"
        )
        or
        job.get(
            "communeNl"
        )
        or
        ""
    )


# ============================================================
# TEST PAR MOT-CLÉ
# ============================================================

def test_keyword(
    keyword
):

    print()

    print(
        "=" * 80
    )

    print(
        f"RECHERCHE : {keyword}"
    )

    print(
        "=" * 80
    )


    results = {}


    for mode in (
        PROVENANCE_MODES
    ):

        print()

        print(
            f"  [{mode}]"
        )


        result = (
            search_with_provenance(
                keyword=
                    keyword,

                provenance_mode=
                    mode,
            )
        )


        results[
            mode
        ] = result


        print(
            f"    Total annoncé : "
            f"{result['total']}"
        )


        print(
            f"    Références récupérées : "
            f"{len(result['jobs'])}"
        )


    # ========================================================
    # SETS
    # ========================================================

    sets = {

        mode:
            set(
                result[
                    "jobs"
                ].keys()
            )

        for mode, result
        in results.items()
    }


    all_refs = (
        sets[
            "ALL"
        ]
    )


    actiris_refs = (
        sets[
            "ACTIRIS"
        ]
    )


    vdab_forem_refs = (
        sets[
            "VDAB_FOREM"
        ]
    )


    partner_refs = (
        sets[
            "PARTNER"
        ]
    )


    handicap_refs = (
        sets[
            "HANDICAP"
        ]
    )


    identified_refs = (
        actiris_refs
        |
        vdab_forem_refs
        |
        partner_refs
        |
        handicap_refs
    )


    unknown_refs = (
        all_refs
        -
        identified_refs
    )


    # ========================================================
    # RÉSUMÉ
    # ========================================================

    print()

    print(
        "-" * 80
    )

    print(
        "RÉPARTITION DES RÉFÉRENCES"
    )

    print(
        "-" * 80
    )


    print(
        f"ALL         : "
        f"{len(all_refs)}"
    )


    print(
        f"ACTIRIS     : "
        f"{len(actiris_refs)}"
    )


    print(
        f"VDAB_FOREM  : "
        f"{len(vdab_forem_refs)}"
    )


    print(
        f"PARTNER     : "
        f"{len(partner_refs)}"
    )


    print(
        f"HANDICAP    : "
        f"{len(handicap_refs)}"
    )


    print(
        f"NON CLASSÉ  : "
        f"{len(unknown_refs)}"
    )


    # ========================================================
    # INTERSECTIONS
    # ========================================================

    print()

    print(
        "-" * 80
    )

    print(
        "INTERSECTIONS ENTRE CATÉGORIES"
    )

    print(
        "-" * 80
    )


    comparisons = [

        (
            "ACTIRIS ∩ VDAB_FOREM",
            actiris_refs
            &
            vdab_forem_refs
        ),

        (
            "ACTIRIS ∩ PARTNER",
            actiris_refs
            &
            partner_refs
        ),

        (
            "ACTIRIS ∩ HANDICAP",
            actiris_refs
            &
            handicap_refs
        ),

        (
            "VDAB_FOREM ∩ PARTNER",
            vdab_forem_refs
            &
            partner_refs
        ),

        (
            "VDAB_FOREM ∩ HANDICAP",
            vdab_forem_refs
            &
            handicap_refs
        ),

        (
            "PARTNER ∩ HANDICAP",
            partner_refs
            &
            handicap_refs
        ),
    ]


    for label, overlap in comparisons:

        print(
            f"{label:<28} : "
            f"{len(overlap)}"
        )


    # ========================================================
    # ÉCHANTILLONS PAR PROVENANCE
    # ========================================================

    for mode in [
        "ACTIRIS",
        "VDAB_FOREM",
        "PARTNER",
        "HANDICAP",
    ]:

        print()

        print(
            "-" * 80
        )

        print(
            f"ÉCHANTILLON {mode}"
        )

        print(
            "-" * 80
        )


        jobs = (
            results[
                mode
            ][
                "jobs"
            ]
        )


        if not jobs:

            print(
                "  [aucune offre]"
            )

            continue


        for reference, job in list(
            jobs.items()
        )[:10]:

            print()

            print(
                f"  {reference}"
            )


            print(
                f"    {get_title(job)}"
            )


            print(
                f"    {get_company(job)}"
            )


            print(
                f"    {get_location(job)}"
            )


            print(
                f"    typeOffre="
                f"{job.get('typeOffre')}"
            )


    return results


# ============================================================
# CLASSIFICATION DES OFFRES TÉMOINS
# ============================================================

def classify_witness_references(
    global_results
):

    print()

    print(
        "=" * 80
    )

    print(
        "CLASSIFICATION DES OFFRES TÉMOINS"
    )

    print(
        "=" * 80
    )


    # référence -> provenance détectée
    reference_modes = defaultdict(
        set
    )


    reference_jobs = {}


    for keyword_results in (
        global_results.values()
    ):

        for mode, result in (
            keyword_results.items()
        ):

            if mode == "ALL":

                continue


            for reference, job in (
                result[
                    "jobs"
                ].items()
            ):

                reference_modes[
                    reference
                ].add(
                    mode
                )


                if (
                    reference
                    not in reference_jobs
                ):

                    reference_jobs[
                        reference
                    ] = job


    for reference, label in (
        WITNESS_REFERENCES.items()
    ):

        print()

        print(
            "-" * 80
        )


        print(
            f"{reference} | {label}"
        )


        modes = (
            reference_modes.get(
                reference,
                set()
            )
        )


        if not modes:

            print(
                "    Provenance : "
                "NON TROUVÉE DANS CES 3 RECHERCHES"
            )

            continue


        print(
            "    Provenance :",
            ", ".join(
                sorted(
                    modes
                )
            )
        )


        job = (
            reference_jobs.get(
                reference
            )
        )


        if job:

            print(
                f"    Titre      : "
                f"{get_title(job)}"
            )


            print(
                f"    Entreprise : "
                f"{get_company(job)}"
            )


            print(
                f"    Lieu       : "
                f"{get_location(job)}"
            )


            print(
                f"    typeOffre  : "
                f"{job.get('typeOffre')}"
            )


# ============================================================
# BILAN GLOBAL
# ============================================================

def print_global_summary(
    global_results
):

    print()

    print(
        "=" * 80
    )

    print(
        "BILAN GLOBAL DE PROVENANCE"
    )

    print(
        "=" * 80
    )


    mode_references = defaultdict(
        set
    )


    for keyword_results in (
        global_results.values()
    ):

        for mode, result in (
            keyword_results.items()
        ):

            for reference in (
                result[
                    "jobs"
                ]
            ):

                mode_references[
                    mode
                ].add(
                    reference
                )


    for mode in [
        "ALL",
        "ACTIRIS",
        "VDAB_FOREM",
        "PARTNER",
        "HANDICAP",
    ]:

        print(
            f"{mode:<12} : "
            f"{len(mode_references[mode])} "
            f"référence(s) unique(s)"
        )


    identified = (

        mode_references[
            "ACTIRIS"
        ]

        |

        mode_references[
            "VDAB_FOREM"
        ]

        |

        mode_references[
            "PARTNER"
        ]

        |

        mode_references[
            "HANDICAP"
        ]
    )


    unknown = (

        mode_references[
            "ALL"
        ]

        -

        identified
    )


    print()

    print(
        "Références ALL non retrouvées "
        "dans une catégorie :",
        len(
            unknown
        )
    )


    if unknown:

        print()

        print(
            "Premières références non classées :"
        )


        for reference in sorted(
            unknown
        )[:30]:

            print(
                "   ",
                reference
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print()

    print(
        "=" * 80
    )

    print(
        "       JOB HUNTER - ACTIRIS PROVENANCE TEST V1"
    )

    print(
        "=" * 80
    )


    global_results = {}


    for keyword in (
        SEARCH_TERMS
    ):

        results = test_keyword(
            keyword
        )


        global_results[
            keyword
        ] = results


    classify_witness_references(
        global_results
    )


    print_global_summary(
        global_results
    )


    print()

    print(
        "=" * 80
    )

    print(
        "TEST TERMINÉ"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":

    main()