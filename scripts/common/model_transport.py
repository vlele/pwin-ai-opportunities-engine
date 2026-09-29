"""Bounded transport recovery and redacted provider diagnostics, not semantic repair."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import math
import os
import random
import re
import time

try:
    from openai import APIConnectionError, APITimeoutError
    NETWORK_ERRORS = (APIConnectionError, APITimeoutError)
except ImportError:
    NETWORK_ERRORS = ()

SAFE_HEADERS = ('retry-after', 'retry-after-ms', 'x-request-id',
                'x-ratelimit-limit-tokens', 'x-ratelimit-remaining-tokens',
                'x-ratelimit-reset-tokens', 'x-ratelimit-remaining-requests',
                'x-ratelimit-reset-requests')
SECRET_FIELD = re.compile(r'^(?:authorization|proxy.authorization|api.?key|.*secret.*|password|access.?token|refresh.?token|token)$', re.I)
QUOTA_CODES = {'insufficient_quota', 'credit_balance_exhausted', 'billing_hard_limit_reached',
               'billing_not_active', 'usage_limit_reached'}
RATE_CODES = {'rate_limit_exceeded', 'rate_limit_error', 'tokens', 'requests'}


def redact(value):
    secrets = [v for k, v in os.environ.items() if v and len(v) >= 4 and
               any(word in k.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]

    def clean(item):
        if isinstance(item, dict):
            return {str(k): '[REDACTED]' if SECRET_FIELD.match(str(k)) else clean(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(v) for v in item]
        if isinstance(item, str):
            for secret in sorted(secrets, key=len, reverse=True):
                item = item.replace(secret, '[REDACTED]')
            item = re.sub(r'\bBearer\s+[^\s,;"\']+', 'Bearer [REDACTED]', item, flags=re.I)
            return re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', item)
        return item if item is None or isinstance(item, (int, float, bool)) else clean(str(item))

    return clean(value)


def error_details(error):
    response = getattr(error, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    body = getattr(error, 'body', None)
    if body is None and response is not None:
        try:
            body = response.json()
        except (ValueError, RuntimeError):
            body = getattr(response, 'text', '')
    detail = body.get('error', body) if isinstance(body, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    return redact({'exception': type(error).__name__, 'http_status': getattr(error, 'status_code', None),
                   'code': detail.get('code', getattr(error, 'code', None)),
                   'type': detail.get('type', getattr(error, 'type', None)),
                   'message': detail.get('message', str(error)), 'body': body,
                   'headers': {key: headers[key] for key in SAFE_HEADERS if key in headers}})


def retry_after_seconds(headers, *, now=None):
    now = time.time() if now is None else now
    values = []
    for key, scale in (('retry-after', 1), ('retry-after-ms', 0.001)):
        value = headers.get(key)
        if value is None:
            continue
        try:
            delay = float(value) * scale
        except (ValueError, TypeError):
            if key != 'retry-after':
                continue
            try:
                parsed = parsedate_to_datetime(value)
                delay = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp() - now
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(delay) and delay >= 0:
            values.append(delay)
    return max(values) if values else None


def _retryable(error, detail, retry_after):
    if isinstance(error, NETWORK_ERRORS):
        return True
    if detail['http_status'] != 429:
        return False
    codes = {str(detail.get(k) or '').lower() for k in ('code', 'type')}
    message = str(detail.get('message') or '').lower()
    if codes & QUOTA_CODES or any(term in message for term in ('credit balance', 'insufficient quota', 'billing hard limit')):
        return False
    # Waiting cannot make an individually oversized request fit a per-minute cap.
    if 'request too large' in message:
        return False
    return bool(codes & RATE_CODES) or retry_after is not None


def create_with_retries(create, *, request, max_retries=3, max_wait_seconds=300,
                        sleep=None, emit=None):
    """Honor server minimum delays; defer instead of shortening an excessive wait."""
    sleep = sleep or time.sleep
    emit = emit or (lambda event: logging.getLogger(__name__).warning('%s', json.dumps(event)))
    waited = 0.0
    for attempt in range(max_retries + 1):
        try:
            return create(**request)
        except Exception as error:
            detail = error_details(error)
            retry_after = retry_after_seconds(detail['headers'])
            retryable = _retryable(error, detail, retry_after)
            delay = max(2 ** attempt + random.uniform(0, 0.25), retry_after or 0)
            decision = ('stop' if not retryable else 'exhausted' if attempt >= max_retries
                        else 'defer' if waited + delay > max_wait_seconds else 'retry')
            try:
                retry_at = datetime.fromtimestamp(time.time() + delay, timezone.utc).isoformat() if retryable else None
            except (ValueError, OverflowError, OSError):
                retry_at = None
            event = {'event': 'provider_transport_error', 'attempt': attempt + 1,
                     'max_attempts': max_retries + 1, 'decision': decision, 'error': detail,
                     'retry_after_seconds': retry_after, 'waited_seconds': waited,
                     'next_retry_at_utc': retry_at,
                     'sleep_seconds': delay if decision == 'retry' else 0}
            emit(event)
            if decision != 'retry':
                raise
            sleep(delay)
            waited += delay
