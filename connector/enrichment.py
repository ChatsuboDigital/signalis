"""
Enrichment Module

Python port of connector-os/src/enrichment/
Enriches records to find missing emails and contact data.

Improvements over original:
- Email verification for pre-existing emails (SSM /verify endpoint)
- Smart input routing: classify inputs before choosing provider
- Apollo seniority ranking: best decision maker, not just first result
- Parallel batch processing (ThreadPoolExecutor, max_workers=3)
- Thread-safe cache access
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# Thread-safe lock for cache reads/writes
_cache_lock = threading.Lock()


# =============================================================================
# SENIORITY RANKING — Apollo candidate scoring
# Port of connector-os seniority ranks. Higher = more senior.
# =============================================================================

SENIORITY_RANKS: Dict[str, int] = {
    'founder': 100,
    'co-founder': 99,
    'owner': 98,
    'partner': 95,
    'principal': 94,
    'managing director': 92,
    'ceo': 90,
    'cfo': 89,
    'cto': 88,
    'coo': 87,
    'cmo': 86,
    'cro': 85,
    'president': 84,
    'vp': 70,
    'vice president': 70,
    'director': 60,
    'head': 55,
    'manager': 40,
    'lead': 35,
    'senior': 30,
}


def _score_person(person: Dict[str, Any]) -> int:
    """Score a candidate by title seniority. Higher = better match."""
    title = (person.get('title') or '').lower()
    for keyword, score in sorted(SENIORITY_RANKS.items(), key=lambda x: -x[1]):
        if keyword in title:
            return score
    return 10  # default for unknown titles


# =============================================================================
# INPUT CLASSIFICATION — Deterministic routing before any API call
# Port of connector-os/src/enrichment/router.ts classifyInputs()
# =============================================================================

def classify_inputs(record: NormalizedRecord) -> str:
    """
    Classify what enrichment action to take based on available inputs.

    Returns one of:
      VERIFY             — email present, check if it's live
      FIND_PERSON        — domain + name, find this specific person
      FIND_COMPANY_CONTACT — domain only, find any decision maker
      SEARCH_PERSON      — company name + person name, no domain
      SEARCH_COMPANY     — company name only, no domain or person
      CANNOT_ROUTE       — insufficient inputs
    """
    has_email = bool(record.email)
    has_domain = bool(record.domain)
    has_company = bool(record.company)

    # Name: full name must be 2+ words, or first + last both set
    name_parts = (record.full_name or '').strip().split()
    has_full_name = len(name_parts) >= 2 or (bool(record.first_name) and bool(record.last_name))

    # Single name with supporting context (title or LinkedIn) still usable
    has_name_with_context = (
        len(name_parts) == 1 and
        (bool(record.title) or bool(record.linkedin))
    )
    has_person_name = has_full_name or has_name_with_context

    if has_email:
        return 'VERIFY'
    if has_domain and has_person_name:
        return 'FIND_PERSON'
    if has_domain:
        return 'FIND_COMPANY_CONTACT'
    if has_company and has_person_name:
        return 'SEARCH_PERSON'
    if has_company:
        return 'SEARCH_COMPANY'
    return 'CANNOT_ROUTE'


# =============================================================================
# PROVIDER FUNCTIONS
# =============================================================================

def verify_with_ssm(
    email: str,
    api_key: str,
    timeout_ms: int = 12000
) -> Optional[EnrichmentResult]:
    """
    Verify an existing email address using the ConnectorAgent verify endpoint.

    Endpoint: POST https://api.connector-os.com/api/email/v2/verify
    SSM membership required: https://www.skool.com/ssmasters

    Returns:
      outcome='VERIFIED'  — email is live (status: valid)
      outcome='VERIFIED'  — email is risky (status: risky) — passes, flagged
      outcome='INVALID'   — email is dead (status: invalid)
      None                — could not determine (error / unknown)
    """
    if not api_key or not email:
        return None

    try:
        response = requests.post(
            'https://api.connector-os.com/api/email/v2/verify',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            json={'email': email},
            timeout=timeout_ms / 1000
        )

        if response.status_code == 401:
            return EnrichmentResult(
                action='VERIFY',
                outcome='AUTH_ERROR',
                email=email,
                source='ssm',
                inputs_present={'email': True}
            )

        if response.status_code == 429:
            return EnrichmentResult(
                action='VERIFY',
                outcome='RATE_LIMITED',
                email=email,
                source='ssm',
                inputs_present={'email': True}
            )

        if response.status_code != 200:
            return None

        data = response.json()
        status = (data.get('status') or '').lower()
        verdict = (data.get('verdict') or '').upper()

        # valid / VALID → confirmed live
        if status == 'valid' or verdict == 'VALID':
            return EnrichmentResult(
                action='VERIFY',
                outcome='VERIFIED',
                email=email,
                verified=True,
                source='ssm',
                inputs_present={'email': True}
            )

        # risky — passes but flagged (verified=False so CSV shows it)
        if status == 'risky':
            return EnrichmentResult(
                action='VERIFY',
                outcome='VERIFIED',
                email=email,
                verified=False,
                source='ssm',
                inputs_present={'email': True}
            )

        # invalid / INVALID → dead address
        if status == 'invalid' or verdict == 'INVALID':
            return EnrichmentResult(
                action='VERIFY',
                outcome='INVALID',
                email=email,
                verified=False,
                source='ssm',
                inputs_present={'email': True}
            )

        # unknown / no status → can't determine, don't block
        return None

    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None


def enrich_with_ssm(
    record: NormalizedRecord,
    api_key: str,
    timeout_ms: int = 18000
) -> Optional[EnrichmentResult]:
    """
    Find email using Connector Agent API (SSM member access).

    SSM membership required — get your API key at:
    https://www.skool.com/ssmasters

    Requires domain + first name + last name.
    Endpoint: POST https://api.connector-os.com/api/email/v2/find
    """
    if not api_key or not record.domain:
        return None

    first_name = record.first_name or (record.full_name.split()[0] if record.full_name else '')
    last_name = record.last_name or (record.full_name.split()[1] if record.full_name and len(record.full_name.split()) > 1 else '')

    if not first_name or not last_name:
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='MISSING_INPUT',
            source='ssm',
            inputs_present={'domain': True, 'person_name': False}
        )

    try:
        response = requests.post(
            'https://api.connector-os.com/api/email/v2/find',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            json={
                'firstName': first_name,
                'lastName': last_name,
                'domain': record.domain,
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

        if response.status_code == 429:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='RATE_LIMITED',
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
            first_name=first_name,
            last_name=last_name,
            title=record.title or '',
            verified=True,
            source='ssm',
            inputs_present={'domain': True, 'person_name': True}
        )

    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None


def enrich_with_apollo(
    record: NormalizedRecord,
    api_key: str,
    timeout_ms: int = 30000
) -> Optional[EnrichmentResult]:
    """
    Find email using Apollo API.

    Scores all candidates by title seniority and picks the best match
    rather than blindly taking the first result.

    Apollo can search by domain OR company name.
    """
    if not api_key:
        return None

    has_domain = bool(record.domain)
    has_company = bool(record.company)

    if not has_domain and not has_company:
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='MISSING_INPUT',
            source='none',
            inputs_present={'domain': False, 'company': False}
        )

    payload: Dict[str, Any] = {
        'contact_email_status': ['verified', 'likely to engage'],
    }

    if has_domain:
        payload['q_organization_domains_list'] = [record.domain]
    else:
        payload['q_keywords'] = record.company

    # Seniority filter: prefer senior people
    payload['person_seniorities'] = [
        'founder', 'c_suite', 'owner', 'partner', 'vp', 'director', 'manager'
    ]

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
                inputs_present={'domain': has_domain, 'company': has_company}
            )

        if response.status_code == 422:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='CREDITS_EXHAUSTED',
                source='apollo',
                inputs_present={'domain': has_domain, 'company': has_company}
            )

        if response.status_code == 429:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='RATE_LIMITED',
                source='apollo',
                inputs_present={'domain': has_domain, 'company': has_company}
            )

        if response.status_code != 200:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NOT_FOUND',
                source='apollo',
                inputs_present={'domain': has_domain, 'company': has_company}
            )

        data = response.json()
        people = data.get('people', [])

        if not people:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NO_CANDIDATES',
                source='apollo',
                inputs_present={'domain': has_domain, 'company': has_company}
            )

        # Rank by seniority — pick the most senior person with an email
        scored = sorted(people, key=_score_person, reverse=True)

        person = None
        email = None
        for candidate in scored:
            candidate_email = candidate.get('email')
            if candidate_email:
                person = candidate
                email = candidate_email
                break

        if not email or not person:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='NO_CANDIDATES',
                source='apollo',
                inputs_present={'domain': has_domain, 'company': has_company}
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
            inputs_present={'domain': has_domain, 'company': has_company}
        )

    except requests.exceptions.Timeout:
        return EnrichmentResult(
            action='FIND_PERSON',
            outcome='TIMEOUT',
            source='apollo',
            inputs_present={'domain': has_domain, 'company': has_company}
        )
    except Exception:
        return None


def enrich_with_anymail(
    record: NormalizedRecord,
    api_key: str,
    timeout_ms: int = 30000
) -> Optional[EnrichmentResult]:
    """
    Find email using Anymail Finder API.

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

        if response.status_code == 429:
            return EnrichmentResult(
                action='FIND_PERSON',
                outcome='RATE_LIMITED',
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

    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None


# =============================================================================
# PROVIDER WATERFALL — ordered by action type
# Port of connector-os router priority matrix
# =============================================================================

def _get_find_providers(config: EnrichmentConfig, action: str):
    """
    Return ordered list of (name, func, api_key) for a given action.

    Priority per action:
      FIND_PERSON:          anymail → ssm → apollo
      FIND_COMPANY_CONTACT: apollo  → anymail
      SEARCH_PERSON:        anymail → apollo
      SEARCH_COMPANY:       apollo  → anymail
    """
    anymail = ('anymail', enrich_with_anymail, config.anymail_api_key)
    apollo  = ('apollo',  enrich_with_apollo,  config.apollo_api_key)
    ssm     = ('ssm',     enrich_with_ssm,     config.ssm_api_key)

    if action == 'FIND_PERSON':
        return [anymail, ssm, apollo]
    elif action == 'FIND_COMPANY_CONTACT':
        return [apollo, anymail]
    elif action == 'SEARCH_PERSON':
        return [anymail, apollo]
    else:  # SEARCH_COMPANY
        return [apollo, anymail]


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
    1. Classify inputs → determine action (VERIFY / FIND_PERSON / etc.)
    2. VERIFY: existing email → call SSM verify endpoint → VERIFIED / INVALID
    3. FIND: check cache first (90-day TTL)
    4. FIND: waterfall through providers in priority order for this action
    5. Cache successful results
    """
    action = classify_inputs(record)

    # ── VERIFY: email already present — check if it's actually live ────────────
    if action == 'VERIFY':
        if config.ssm_api_key:
            verify_result = verify_with_ssm(record.email, config.ssm_api_key)
            if verify_result:
                return verify_result

        # No verify key configured or verify returned None (unknown) — trust it
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

    # ── CANNOT_ROUTE: nothing to work with ────────────────────────────────────
    if action == 'CANNOT_ROUTE':
        return EnrichmentResult(
            action='CANNOT_ROUTE',
            outcome='MISSING_INPUT',
            source='none',
            inputs_present={
                'email': False,
                'domain': bool(record.domain),
                'company': bool(record.company),
                'person_name': bool(record.first_name or record.full_name),
            }
        )

    # ── FIND: check cache first ────────────────────────────────────────────────
    with _cache_lock:
        cached_result = check_cache(record)

    if cached_result:
        record.email = cached_result.email
        if cached_result.first_name:
            record.first_name = cached_result.first_name
        if cached_result.last_name:
            record.last_name = cached_result.last_name
        if cached_result.title:
            record.title = cached_result.title
        return cached_result

    # ── FIND: waterfall through providers ─────────────────────────────────────
    providers = _get_find_providers(config, action)

    for provider_name, provider_func, api_key in providers:
        if not api_key:
            continue

        result = provider_func(record, api_key, config.timeout_ms)

        if result and result.outcome == 'ENRICHED':
            record.email = result.email
            if result.first_name:
                record.first_name = result.first_name
            if result.last_name:
                record.last_name = result.last_name
            if result.title:
                record.title = result.title

            with _cache_lock:
                store_in_cache(record, result)

            return result

        # Stop cascading on auth/credit errors — no point trying same provider again
        if result and result.outcome in ('AUTH_ERROR', 'CREDITS_EXHAUSTED'):
            break

    return EnrichmentResult(
        action=action,
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
    Enrich multiple records in parallel (max 3 concurrent API calls).

    Returns dict mapping record_key → EnrichmentResult
    """
    results: Dict[str, EnrichmentResult] = {}
    completed = 0
    progress_lock = threading.Lock()
    total = len(records)

    def _enrich_one(record: NormalizedRecord):
        return record.record_key, enrich_record(record, config)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_enrich_one, record): record for record in records}

        for future in as_completed(futures):
            record_key, result = future.result()
            results[record_key] = result

            if on_progress:
                with progress_lock:
                    completed += 1
                    on_progress(completed, total)

    return results
