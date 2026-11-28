"""Rule-based labelling before the LLM, for traffic that is unambiguous.

Deliberately conservative: a false negative costs a few tokens, a false
positive hides an interview invite. Default rules require a known sender/domain plus digest evidence and no
important application/interview signal. Explicit user rules retain their intent.
List-Unsubscribe headers alone never identify noise: ATS platforms set them too.
"""

from __future__ import annotations

import re

from .config import PrefilterRule
from .models import Classification, NormalizedMessage

#: Known job-board senders; shared senders still require digest evidence.
DEFAULT_ALERT_SENDERS = {
    "jobalerts-noreply@linkedin.com",
    "jobs-listings@linkedin.com",
    "jobs-noreply@linkedin.com",
    "alert@indeed.com",
    "alerts@indeed.com",
    "noreply@indeed.com",
    "invitetoapply@indeed.com",
    "no-reply@ziprecruiter.com",
    "jobs@ziprecruiter.com",
    "alerts@glassdoor.com",
    "noreply@glassdoor.com",
    "jobalerts@monster.com",
    "alerts@dice.com",
    "notifications@talent.com",
    "jobs@weworkremotely.com",
}

DEFAULT_ALERT_DOMAINS = {
    "jobalerts.linkedin.com",
    "e.linkedin.com",
}


# Evidence permits skipping the model, never forces an interview/receipt label.
_DIGEST = re.compile(r"\b(?:job (?:digest|alert)|jobs matching your search|new jobs for|saved.search alert|recommended jobs)\b", re.I)
_IMPORTANT = re.compile(
    r"\b(?:interview|phone screen|assessment|offer|rejected|rejection|other candidates|"
    r"application (?:received|submitted|confirmation|update)|"
    r"(?:received|reviewing|thank you for|thanks for) (?:your )?(?:application|applying))\b", re.I)


def important_evidence(msg: NormalizedMessage) -> bool:
    return bool(_IMPORTANT.search(msg.subject + "\n" + msg.body))


def _match(rule: PrefilterRule, msg: NormalizedMessage) -> bool:
    if rule.sender and msg.from_addr.lower() != rule.sender.lower():
        return False
    if rule.sender_domain:
        domain = msg.from_addr.rsplit("@", 1)[-1].lower()
        if domain != rule.sender_domain.lower():
            return False
    if rule.subject_contains and rule.subject_contains.lower() not in msg.subject.lower():
        return False
    # A rule with no conditions must never match everything.
    return any([rule.sender, rule.sender_domain, rule.subject_contains])


def apply(
    msg: NormalizedMessage, rules: list[PrefilterRule] | None = None
) -> Classification | None:
    """Return a Classification to skip the LLM, or None to let it through."""
    for rule in rules or []:
        if _match(rule, msg):
            return Classification(
                category=rule.category,
                confidence=1.0,
                summary="Matched a local prefilter rule.",
                source="prefilter",
            )

    addr = msg.from_addr.lower()
    domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
    if ((addr in DEFAULT_ALERT_SENDERS or domain in DEFAULT_ALERT_DOMAINS)
            and _DIGEST.search(msg.subject + "\n" + msg.body)
            and not important_evidence(msg)):
        return Classification(
            category="job_alert",
            confidence=1.0,
            summary="Job board digest (matched a known alert sender).",
            source="prefilter",
        )
    return None
