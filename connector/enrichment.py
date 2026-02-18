"""
Enrichment Module

Python port of connector-os/src/enrichment/
Enriches records to find missing emails and contact data.
"""

import requests
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .models import NormalizedRecord, EnrichmentResult
from .enrichment_cache import check_cache, store_in_cache


@dataclass
class EnrichmentConfig:
    """Configuration for enrichment providers"""
    apollo_api_key: Optional[str] = None
    anymail_api_key: Optional[str] = None
    ssm_api_key: Optional[str] = None
    timeout_ms: int = 30000


# =============================================================================
# PROVIDER FUNCTIONS
# =============================================================================

def enrich_with_ssm(
    record: NormalizedRecord,
    api_key: str,
    timeout_ms: int = 30000
) -> Optional[EnrichmentResult]:
    """
    Enrich record using SSM member API.

    SSM membership required — get your API key at:
    https://www.skool.com/ssmasters

    Searches by domain + person name.
    """
    if not api_key or not record.domain:
        return None

    if not (record.first_name or record.full_name):
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='MISSING_INPUT',
            source='none',
            inputs_present={'domain': bool(record.domain), 'person_name': False}
        )

    first_name = record.first_name or record.full_name.split()[0]
    last_name = record.last_name or (record.full_name.split()[1] if len(record.full_name.split()) > 1 else '')

    try:
        response = requests.post(
            'https://api.ssm.chatsubo.digital/v1/enrich',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            json={
                'domain': record.domain,
                'first_name': first_name,
                'last_name': last_name,
                'company': record.company,
            },
            timeout=timeout_ms / 1000
        )

        if response.status_code == 401:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='AUTH_ERROR',
                source='ssm',
                inputs_present={'domain': True, 'person_name': True}
            )

        if response.status_code != 200:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NOT_FOUND',
                source='ssm',
                inputs_present={'domain': True, 'person_name': True}
            )

        data = response.json()
        email = data.get('email')

        if not email:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NO_CANDIDATES',
                source='ssm',
                inputs_present={'domain': True, 'person_name': True}
            )

        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='ENRICHED',
            email=email,
            first_name=data.get('first_name', first_name),
            last_name=data.get('last_name', last_name),
            title=data.get('title', record.title or ''),
            verified=True,
            source='ssm',
            inputs_present={'domain': True, 'person_name': True}
        )

    except Exception:
        return None


def enrich_with_apollo(
    record: NormalizedRecord,
    api_key: str,
    timeout_ms: int = 30000
) -> Optional[EnrichmentResult]:
    """
    Enrich record using Apollo API.

    Apollo can search by domain OR company.
    """
    if not api_key:
        return None

    # Build request payload
    payload: Dict[str, Any] = {}

    if record.domain:
        payload['domain'] = record.domain
    elif record.company:
        payload['organization_name'] = record.company
    else:
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='MISSING_INPUT',
            source='none',
            inputs_present={'domain': False, 'company': False}
        )

    # Add person filters if available
    if record.first_name or record.full_name:
        payload['person_titles'] = [record.title] if record.title else []

    try:
        response = requests.post(
            'https://api.apollo.io/v1/mixed_people/search',
            headers={
                'Content-Type': 'application/json',
                'X-Api-Key': api_key,
            },
            json=payload,
            timeout=timeout_ms / 1000
        )

        if response.status_code == 401:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='AUTH_ERROR',
                source='apollo',
                inputs_present={'domain': bool(record.domain), 'company': bool(record.company)}
            )

        if response.status_code != 200:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NOT_FOUND',
                source='apollo',
                inputs_present={'domain': bool(record.domain), 'company': bool(record.company)}
            )

        data = response.json()
        people = data.get('people', [])

        if not people:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NO_CANDIDATES',
                source='apollo',
                inputs_present={'domain': bool(record.domain), 'company': bool(record.company)}
            )

        # Get first person
        person = people[0]
        email = person.get('email')

        if not email:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NO_CANDIDATES',
                source='apollo',
                inputs_present={'domain': bool(record.domain), 'company': bool(record.company)}
            )

        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='ENRICHED',
            email=email,
            first_name=person.get('first_name', ''),
            last_name=person.get('last_name', ''),
            title=person.get('title', ''),
            verified=True,
            source='apollo',
            inputs_present={'domain': bool(record.domain), 'company': bool(record.company)}
        )

    except Exception as e:
        # Log error silently - enrichment failures are expected and handled
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='TIMEOUT',
            source='apollo',
            inputs_present={'domain': bool(record.domain), 'company': bool(record.company)}
        )


def enrich_with_anymail(
    record: NormalizedRecord,
    api_key: str,
    timeout_ms: int = 30000
) -> Optional[EnrichmentResult]:
    """
    Enrich record using Anymail Finder API.

    Anymail requires domain + name.
    """
    if not api_key or not record.domain:
        return None

    if not (record.first_name or record.full_name):
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='MISSING_INPUT',
            source='none',
            inputs_present={'domain': bool(record.domain), 'person_name': False}
        )

    # Build request
    first_name = record.first_name or record.full_name.split()[0]
    last_name = record.last_name or (record.full_name.split()[1] if len(record.full_name.split()) > 1 else '')

    try:
        response = requests.get(
            'https://api.anymailfinder.com/v5.0/search/person.json',
            params={
                'api_key': api_key,
                'email_domain': record.domain,
                'first_name': first_name,
                'last_name': last_name,
            },
            timeout=timeout_ms / 1000
        )

        if response.status_code == 401:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='AUTH_ERROR',
                source='anymail',
                inputs_present={'domain': True, 'person_name': True}
            )

        if response.status_code != 200:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NOT_FOUND',
                source='anymail',
                inputs_present={'domain': True, 'person_name': True}
            )

        data = response.json()
        email = data.get('email')

        if not email or data.get('confidence', 0) < 50:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NO_CANDIDATES',
                source='anymail',
                inputs_present={'domain': True, 'person_name': True}
            )

        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='ENRICHED',
            email=email,
            first_name=first_name,
            last_name=last_name,
            title=record.title or '',
            verified=True,
            source='anymail',
            inputs_present={'domain': True, 'person_name': True}
        )

    except Exception as e:
        # Silently fail on network/API errors
        return None


# =============================================================================
# MAIN ENRICHMENT FUNCTION
# =============================================================================

def enrich_record(
    record: NormalizedRecord,
    config: EnrichmentConfig
) -> EnrichmentResult:
    """
    Enrich a single record.

    FLOW:
    1. If email exists, return immediately (trust user data)
    2. Check cache for previous enrichment
    3. Waterfall through providers: Apollo → Anymail → SSM
    4. Store successful results in cache
    5. Return first successful enrichment

    Returns EnrichmentResult with action and outcome.
    """
    # If email already exists, trust it
    if record.email:
        return EnrichmentResult(
            action='VERIFY',
            outcome='ENRICHED',
            email=record.email,
            first_name=record.first_name,
            last_name=record.last_name,
            title=record.title or '',
            verified=True,
            source='existing',
            inputs_present={'email': True}
        )

    # Check cache first (90-day TTL)
    cached_result = check_cache(record)
    if cached_result:
        # Update record with cached data
        record.email = cached_result.email
        if cached_result.first_name:
            record.first_name = cached_result.first_name
        if cached_result.last_name:
            record.last_name = cached_result.last_name
        if cached_result.title:
            record.title = cached_result.title
        return cached_result

    # Try providers in order
    providers = [
        ('apollo', enrich_with_apollo, config.apollo_api_key),
        ('anymail', enrich_with_anymail, config.anymail_api_key),
        ('ssm', enrich_with_ssm, config.ssm_api_key),
    ]

    for provider_name, provider_func, api_key in providers:
        if not api_key:
            continue

        result = provider_func(record, api_key, config.timeout_ms)

        if result and result.outcome == 'ENRICHED':
            # Update record with enriched data
            record.email = result.email
            if result.first_name:
                record.first_name = result.first_name
            if result.last_name:
                record.last_name = result.last_name
            if result.title:
                record.title = result.title

            # Store in cache for future use
            store_in_cache(record, result)

            return result

    # No provider succeeded
    return EnrichmentResult(
        action='FIND_PERSON',
        outcome='NOT_FOUND',
        source='none',
        inputs_present={
            'domain': bool(record.domain),
            'company': bool(record.company),
            'person_name': bool(record.first_name or record.full_name),
        }
    )


def enrich_batch(
    records: List[NormalizedRecord],
    config: EnrichmentConfig,
    on_progress: Optional[callable] = None
) -> Dict[str, EnrichmentResult]:
    """
    Enrich multiple records.

    Returns dict mapping record_key → EnrichmentResult
    """
    results = {}

    for i, record in enumerate(records):
        result = enrich_record(record, config)
        results[record.record_key] = result

        if on_progress:
            on_progress(i + 1, len(records))

    return results
