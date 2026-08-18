"""Diagnostic synthétique Recall Rescue V1, sans réseau."""

from diagnostics.recall_rescue_v1 import unique_high_risk_items, audit_item_to_job


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def main():
    audit = {
        "high_recall_risk_items": [
            {
                "raw_job_id": 1,
                "source": "FOREM",
                "collection_channel": "FOREM",
                "origin_source": "FOREM",
                "external_id": "123",
                "title": "Technicien qualité",
                "company": "Test",
                "location": "Bruxelles, Belgique",
                "url": "https://example.test/123",
                "watch_buckets": ["QC_QUALITY"],
                "matcher_core_relevance": False,
                "matcher_score": 0,
                "matcher_family": "data_analytics",
                "matcher_reasons": ["Aucun signal métier suffisant"],
            },
            {
                "raw_job_id": 2,
                "source": "FOREM",
                "external_id": "123",
                "title": "Doublon",
            },
        ]
    }

    tests = []
    items = unique_high_risk_items(audit)
    tests.append(check("Dédup source/external_id", len(items) == 1, str(len(items))))

    job = audit_item_to_job(items[0])
    tests.append(check("JobOffer source", job.source == "FOREM", job.source))
    tests.append(check("JobOffer external_id", job.external_id == "123", job.external_id))
    tests.append(check("Titre conservé", job.title == "Technicien qualité", job.title))
    tests.append(check("Eligibilité standard initiale", job.source_eligibility_status == "ELIGIBLE"))
    tests.append(check("Aucune description inventée", job.description == ""))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")
    if all(tests):
        print("✅ RECALL RESCUE V1 VALIDÉ SUR LE DIAGNOSTIC LOCAL.")
    else:
        raise SystemExit("❌ RECALL RESCUE V1 NON VALIDÉ.")


if __name__ == "__main__":
    main()
