"""
VDAB API readiness V1.

The official Vacature 4.2.0 endpoint is account/plan based and uses
ibm-api-key + X-IBM-Client-Id headers. V7 stores and validates credential
presence but deliberately does not guess the account-gated search schema.

Once credentials are configured, the next batch can validate the downloaded
OpenAPI spec from the user's subscribed product and activate the collector.
"""

from __future__ import annotations

from sources.api_credentials import credential_status

SOURCE_KEY="VDAB"
BASE="https://api.vdab.be/services/openservices/vacatures/v4.2.0"


def get_vdab_readiness() -> dict:
    status=credential_status(SOURCE_KEY)
    return {
        **status,
        "endpoint":BASE,
        "activation_state":"READY_FOR_SCHEMA_VALIDATION" if status["ready"] else "NEEDS_CREDENTIALS",
    }
