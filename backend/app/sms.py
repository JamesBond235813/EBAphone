"""Phone-number and SMS verification service.

The supplied PHP service uses six-digit, five-minute codes and two fixed
development numbers.  This module preserves those semantics while storing
numbers in one canonical Ghana format (``+233XXXXXXXXX``), enforcing resend
cooldowns, and providing an optional HTTP provider adapter for production.
"""

from __future__ import annotations

import os
import secrets
import time
import asyncio
import hashlib
import hmac
import json
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

CODE_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = max(0, int(os.getenv("SMS_RESEND_COOLDOWN_SECONDS", "60")))
MAX_SENDS_PER_HOUR = max(1, int(os.getenv("SMS_MAX_SENDS_PER_HOUR", "5")))
MAX_VERIFY_ATTEMPTS = max(1, int(os.getenv("SMS_MAX_VERIFY_ATTEMPTS", "5")))
MAX_TRACKED_NUMBERS = max(100, int(os.getenv("SMS_MAX_TRACKED_NUMBERS", "10000")))
TEST_NUMBERS = {"0888888888", "0666666666"}
OTP_HASH_SECRET = os.getenv("OTP_HASH_SECRET", "ebaphone-development-otp-secret-change-me")


class SmsRateLimitError(RuntimeError):
    """A verification-code request was throttled for a known duration."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


@dataclass(slots=True)
class _Code:
    value: str
    expires_at: float
    sent_at: float
    attempts: int = 0


_codes: dict[str, _Code] = {}
# This lock makes the check-and-reserve operation atomic for all coroutines and
# threads in one process.  Production should still use a shared Redis/database
# store for cross-process OTP state; the in-memory fallback is intentionally
# bounded so a phone-number spray cannot grow without limit.
_send_history: dict[str, deque[float]] = {}
_state_lock = asyncio.Lock()


def _otp_hash(phone: str, code: str) -> str:
    """Hash a code so a database dump cannot directly reveal active OTPs."""

    return hmac.new(OTP_HASH_SECRET.encode("utf-8"), f"{phone}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _utc_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).timestamp()
    return value.timestamp()


def _parse_history(value: str | None, now: float) -> list[float]:
    try:
        parsed = json.loads(value or "[]")
        history = [float(item) for item in parsed if isinstance(item, (int, float, str))]
    except (TypeError, ValueError, json.JSONDecodeError):
        history = []
    return [item for item in history if math.isfinite(item) and 0 <= now - item < 3600]


def _runtime_environment() -> str:
    # An omitted environment is treated as production so fixed test numbers
    # and in-memory OTP shortcuts cannot be enabled accidentally.  Local
    # development should declare APP_ENV=development explicitly.
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()


def _test_numbers_enabled() -> bool:
    return _runtime_environment() in {"development", "testing"}


def _ascii_digits(value: object) -> bool:
    return isinstance(value, str) and bool(value) and all("0" <= char <= "9" for char in value)


def _digits(phone: str) -> str:
    # Accept common visual separators copied from contact forms, but reject
    # alphabetic and Unicode digit lookalikes instead of silently changing the
    # number that will be used as an account identifier.
    raw = str(phone).strip()
    if not raw or any(char not in "0123456789+()-. \t" for char in raw):
        return ""
    return "".join(char for char in raw if "0" <= char <= "9")


def normalize(phone: str) -> str:
    """Normalize a Ghana mobile number to ``+233`` plus nine digits.

    Accepted inputs include ``0241234567``, ``241234567``, ``233241234567``
    and ``+233 24 123 4567``.  A ``ValueError`` is raised for malformed
    values so API schemas can return a useful 422 response.
    """

    raw = str(phone or "").strip()
    digits = _digits(raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("233"):
        national = digits[3:]
    elif len(digits) == 10 and digits.startswith("0"):
        national = digits[1:]
    elif len(digits) == 9:
        national = digits
    else:
        raise ValueError("Enter a valid Ghana phone number")
    if len(national) != 9 or not _ascii_digits(national):
        raise ValueError("Enter a valid Ghana phone number")
    return f"+233{national}"


def _legacy_test_number(phone: str) -> bool:
    if not _test_numbers_enabled():
        return False
    try:
        canonical = normalize(phone)
    except ValueError:
        return False
    return canonical in {"+233888888888", "+233666666666"}


def _prune_history(phone: str, now: float) -> deque[float]:
    history = _send_history.get(phone)
    if history is None:
        return deque()
    while history and now - history[0] >= 3600:
        history.popleft()
    return history


def _trim_state_locked(now: float) -> None:
    """Drop expired/old in-memory state to keep the fallback bounded."""

    for phone, item in list(_codes.items()):
        if now >= item.expires_at:
            _codes.pop(phone, None)
    for phone, history in list(_send_history.items()):
        _prune_history(phone, now)
        if not history and phone not in _codes:
            _send_history.pop(phone, None)

    # Evict the oldest tracked numbers if a hostile caller rotates through
    # more numbers than the in-memory safety cap.  Redis/database storage is
    # still required for reliable multi-worker production deployments.
    while len(_send_history) > MAX_TRACKED_NUMBERS:
        oldest = next(iter(_send_history))
        _send_history.pop(oldest, None)
        _codes.pop(oldest, None)


async def _send_provider(phone: str, code: str) -> str:
    """Send through an optional generic JSON SMS gateway.

    The gateway contract is intentionally tiny so it can be adapted to the
    local Ghana provider without changing the auth flow.  When no provider is
    configured, development uses a deterministic simulated delivery.
    """

    url = os.getenv("SMS_PROVIDER_URL", "").strip()
    token = os.getenv("SMS_PROVIDER_TOKEN", "").strip()
    if not url:
        if _runtime_environment() in {"production", "prod"}:
            raise RuntimeError("SMS provider is not configured")
        return "simulated"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "to": phone,
        "message": os.getenv("SMS_MESSAGE_TEMPLATE", "Your EBAphone verification code is {code}").format(code=code),
        "from": os.getenv("SMS_PROVIDER_FROM", "EBAphone"),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
    return "provider"


async def _send_code_memory(phone: str) -> dict:
    try:
        canonical = normalize(phone)
    except ValueError as exc:
        # Keep this module framework-agnostic; main.py maps ValueError to 422.
        raise ValueError(str(exc)) from exc

    now = time.time()
    is_test_number = _legacy_test_number(phone)
    async with _state_lock:
        _trim_state_locked(now)
        history = _prune_history(canonical, now)
        last_sent = history[-1] if history else None
        if last_sent is not None and not is_test_number and now - last_sent < RESEND_COOLDOWN_SECONDS:
            retry_after = int(RESEND_COOLDOWN_SECONDS - (now - last_sent)) + 1
            raise SmsRateLimitError(
                f"Please wait {retry_after} seconds before requesting another code",
                retry_after,
            )
        if len(history) >= MAX_SENDS_PER_HOUR and not is_test_number:
            retry_after = int(3600 - (now - history[0])) + 1
            raise SmsRateLimitError("Too many verification requests; try again later", retry_after)

        code = "888888" if is_test_number else f"{secrets.randbelow(1_000_000):06d}"
        reservation = _Code(value=code, expires_at=now + CODE_TTL_SECONDS, sent_at=now)
        _codes[canonical] = reservation
        history = _send_history.setdefault(canonical, deque())
        history.append(now)
        _trim_state_locked(now)

    try:
        delivery = await _send_provider(canonical, code)
    except Exception:
        # Do not leave a code or quota timestamp behind when the provider did
        # not accept the message.  Only roll back our own reservation in case a
        # development test number was sent again while this request awaited.
        async with _state_lock:
            if _codes.get(canonical) is reservation:
                _codes.pop(canonical, None)
                current_history = _send_history.get(canonical)
                if current_history:
                    current_history.pop()
                    if not current_history:
                        _send_history.pop(canonical, None)
        raise

    result: dict[str, object] = {
        "phone": canonical,
        "expires_in": CODE_TTL_SECONDS,
        "retry_after": RESEND_COOLDOWN_SECONDS,
        "delivery": delivery,
    }
    # Fixed test numbers are safe to expose in development and keep the
    # acceptance flow usable without a real SMS gateway.  Never expose random
    # codes for ordinary numbers.
    expose_test_code = os.getenv("SMS_EXPOSE_TEST_CODE", "true").strip().lower() in {"1", "true", "yes"}
    if is_test_number and _test_numbers_enabled() and expose_test_code:
        result["test_code"] = code
    return result


async def _verify_code_memory(phone: str, code: str) -> bool:
    try:
        canonical = normalize(phone)
    except ValueError:
        return False
    now = time.time()
    async with _state_lock:
        _trim_state_locked(now)
        item = _codes.get(canonical)
        if not item or now > item.expires_at:
            _codes.pop(canonical, None)
            return False
        if not isinstance(code, str) or len(code) != 6 or not _ascii_digits(code):
            item.attempts += 1
            if item.attempts >= MAX_VERIFY_ATTEMPTS:
                _codes.pop(canonical, None)
            return False
        if secrets.compare_digest(item.value, code):
            _codes.pop(canonical, None)
            # Keep the independent send history so a successful verification
            # cannot be used to reset the hourly quota/cooldown.
            return True
        item.attempts += 1
        if item.attempts >= MAX_VERIFY_ATTEMPTS:
            _codes.pop(canonical, None)
        return False


async def _send_code_database(phone: str, db: AsyncSession, *, retry: bool = True) -> dict:
    """Persist an OTP challenge and send it without storing the clear code."""

    from .models import SmsChallenge

    try:
        canonical = normalize(phone)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    now = time.time()
    is_test_number = _legacy_test_number(phone)
    challenge = await db.scalar(
        select(SmsChallenge).where(SmsChallenge.phone == canonical).with_for_update()
    )
    history = _parse_history(challenge.send_history if challenge else None, now)
    if challenge and now >= _timestamp(challenge.expires_at) and not history:
        # Reclaim stale rows after their one-hour quota window has elapsed;
        # otherwise a number spray would leave permanent tombstones.
        await db.delete(challenge)
        await db.flush()
        challenge = None
    last_sent = max(history) if history else None
    if last_sent is not None and not is_test_number and now - last_sent < RESEND_COOLDOWN_SECONDS:
        retry_after = int(RESEND_COOLDOWN_SECONDS - (now - last_sent)) + 1
        raise SmsRateLimitError(
            f"Please wait {retry_after} seconds before requesting another code",
            retry_after,
        )
    if len(history) >= MAX_SENDS_PER_HOUR and not is_test_number:
        retry_after = int(3600 - (now - min(history))) + 1
        raise SmsRateLimitError("Too many verification requests; try again later", retry_after)

    code = "888888" if is_test_number else f"{secrets.randbelow(1_000_000):06d}"
    reservation_id = secrets.token_hex(16)
    previous = None
    if challenge:
        previous = {
            "code_hash": challenge.code_hash,
            "reservation_id": challenge.reservation_id,
            "expires_at": challenge.expires_at,
            "sent_at": challenge.sent_at,
            "attempts": challenge.attempts,
            "send_history": challenge.send_history,
        }
    else:
        challenge = SmsChallenge(phone=canonical)
    challenge.code_hash = _otp_hash(canonical, code)
    challenge.reservation_id = reservation_id
    challenge.expires_at = _utc_datetime(now + CODE_TTL_SECONDS)
    challenge.sent_at = _utc_datetime(now)
    challenge.attempts = 0
    challenge.send_history = json.dumps(history + [now], separators=(",", ":"))
    db.add(challenge)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Two workers can both observe an absent phone row.  Retry once after
        # the winner has inserted it; the second pass then applies cooldown
        # and quota rules against the persisted state.
        if retry:
            return await _send_code_database(phone, db, retry=False)
        raise RuntimeError("Unable to reserve a verification code") from exc

    try:
        delivery = await _send_provider(canonical, code)
    except Exception:
        # Roll back only our reservation.  A later request may have replaced
        # it (possible for development test numbers, which bypass cooldown).
        try:
            current = await db.scalar(
                select(SmsChallenge).where(SmsChallenge.phone == canonical).with_for_update()
            )
            if current and current.reservation_id == reservation_id:
                if previous is None:
                    await db.delete(current)
                else:
                    for key, value in previous.items():
                        setattr(current, key, value)
                await db.commit()
        except Exception:
            await db.rollback()
        raise

    result: dict[str, object] = {
        "phone": canonical,
        "expires_in": CODE_TTL_SECONDS,
        "retry_after": RESEND_COOLDOWN_SECONDS,
        "delivery": delivery,
    }
    expose_test_code = os.getenv("SMS_EXPOSE_TEST_CODE", "true").strip().lower() in {"1", "true", "yes"}
    if is_test_number and _test_numbers_enabled() and expose_test_code:
        result["test_code"] = code
    return result


async def _verify_code_database(phone: str, code: str, db: AsyncSession) -> bool:
    from .models import SmsChallenge

    try:
        canonical = normalize(phone)
    except ValueError:
        return False
    now = time.time()
    item = await db.scalar(
        select(SmsChallenge).where(SmsChallenge.phone == canonical).with_for_update()
    )
    if not item:
        return False
    if now >= _timestamp(item.expires_at):
        # Keep the independent send history after expiry so a successful or
        # expired challenge cannot reset the hourly quota.  Remove the row
        # only when no recent history remains.
        if _parse_history(item.send_history, now):
            item.code_hash = ""
            item.attempts = 0
        else:
            await db.delete(item)
        await db.commit()
        return False
    valid_format = isinstance(code, str) and len(code) == 6 and _ascii_digits(code)
    valid_code = valid_format and hmac.compare_digest(item.code_hash, _otp_hash(canonical, code))
    if valid_code:
        item.code_hash = ""
        item.attempts = 0
        await db.commit()
        return True
    item.attempts = int(item.attempts or 0) + 1
    if item.attempts >= MAX_VERIFY_ATTEMPTS:
        item.code_hash = ""
    await db.commit()
    return False


async def send_code(phone: str, db: AsyncSession | None = None) -> dict:
    """Issue an OTP, using persistent database state when a request session is supplied."""

    if db is not None:
        return await _send_code_database(phone, db)
    if _runtime_environment() in {"production", "prod"}:
        raise RuntimeError("Persistent OTP storage is required in production")
    return await _send_code_memory(phone)


async def verify_code(phone: str, code: str, db: AsyncSession | None = None) -> bool:
    """Verify and consume an OTP from persistent or in-memory storage."""

    if db is not None:
        return await _verify_code_database(phone, code, db)
    if _runtime_environment() in {"production", "prod"}:
        return False
    return await _verify_code_memory(phone, code)


def clear_codes() -> None:
    """Clear only the in-memory fallback state (database challenges are persistent)."""

    _codes.clear()
    _send_history.clear()
