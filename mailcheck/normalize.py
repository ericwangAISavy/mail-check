"""MIME text -> clean plain text.

This stage directly controls both LLM cost and accuracy: everything it strips
is a token not spent, and quoted history is the main source of misclassification
(a reply to a rejection still contains the original rejection text).
"""

from __future__ import annotations

import re
import html

import html2text

from .models import NormalizedMessage, RawMessage

_HTML_HINT = re.compile(r"<(?:html|body|div|table|p|br|a)\b", re.I)

# Where quoted history begins. Everything from the first hit onward is dropped.
_QUOTE_MARKERS = [
    re.compile(r"^\s*On .{0,200}\bwrote:\s*$", re.I | re.M),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.I | re.M),
    re.compile(r"^\s*-{3,}\s*Forwarded message\s*-{3,}\s*$", re.I | re.M),
    re.compile(r"^\s*_{10,}\s*$", re.M),
    re.compile(r"^\s*From:.*\n\s*Sent:.*\n", re.I | re.M),
    re.compile(r"^\s*El .{0,200}\bescribió:\s*$", re.I | re.M),
]

# Footer boilerplate. Only cut if it appears late in the body, so an email whose
# whole point is "unsubscribe" is not reduced to nothing.
_FOOTER_MARKERS = [
    re.compile(r"\bunsubscribe\b", re.I),
    re.compile(r"you (?:are )?receiv(?:ed|ing) this (?:email|message)", re.I),
    re.compile(r"this (?:e-?mail|message) was sent to\b", re.I),
    re.compile(r"confidentialit(?:y|é) notice", re.I),
    re.compile(r"this (?:e-?mail|message) (?:and any attachments )?(?:is|are) confidential", re.I),
    re.compile(r"^\s*sent from my (?:iphone|ipad|android|samsung)", re.I | re.M),
]

_URL = re.compile(r"https?://\S+")
_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+$", re.M)


def _html_to_text(html: str) -> str:
    h = html2text.HTML2Text()
    h.body_width = 0          # no hard wrapping - it fragments sentences
    h.ignore_images = True
    h.ignore_links = False    # Calendly / HackerRank links carry real signal
    h.ignore_emphasis = True
    h.skip_internal_links = True
    return h.handle(html)


def _strip_quotes(text: str) -> str:
    cut = len(text)
    for marker in _QUOTE_MARKERS:
        m = marker.search(text)
        if m and m.start() < cut:
            cut = m.start()
    text = text[:cut]
    # Drop residual `>` quote lines.
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines)


def _strip_footer(text: str) -> str:
    # Only cut a marker that sits late in the body AND leaves real content
    # behind, so a short email whose whole point is "unsubscribe" survives.
    threshold = max(120, int(len(text) * 0.5))
    if len(text) <= threshold:
        return text
    cut = len(text)
    for marker in _FOOTER_MARKERS:
        for m in marker.finditer(text):
            if m.start() >= threshold:
                cut = min(cut, m.start())
                break
    return text[:cut]


def _shorten_urls(text: str, max_len: int = 90) -> str:
    def repl(m: re.Match[str]) -> str:
        url = m.group(0)
        if len(url) <= max_len:
            return url
        # Keep scheme+host+start of path; tracking query strings are pure burn.
        return url[:max_len] + "..."

    return _URL.sub(repl, text)


def clean_text(raw: str) -> str:
    text = raw or ""
    if _HTML_HINT.search(text):
        text = _html_to_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("‌", "").replace(" ", " ")  # zero-width, nbsp
    text = _strip_quotes(text)
    text = _strip_footer(text)
    text = _shorten_urls(text)
    text = _TRAILING_WS.sub("", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def normalize(
    raw: RawMessage, *, account_id: int, account_label: str, max_body_chars: int = 1200
) -> NormalizedMessage:
    body = clean_text(raw.text)
    # Recover a small quote only for context-free replies. A substantive latest
    # message must not inherit an old invitation or decision from its thread.
    context_reply = re.search(
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|"
        r"available|availability|works|confirmed|sounds good|see attached|see below)\b", body, re.I
    )
    if len(body) < 80 and context_reply and not re.search(
        r"interview|application|candidates|declin|reject|offer|assessment|not (?:to )?(?:proceed|move forward)|unsuccessful|position.{0,20}(?:closed|filled)", body, re.I
    ):
        original = _html_to_text(raw.text) if _HTML_HINT.search(raw.text or "") else (raw.text or "")
        quoted = "\n".join(line.lstrip().lstrip(">").strip()
                           for line in original.splitlines() if line.lstrip().startswith(">"))
        if quoted:
            body += "\n[Quoted context — earlier message, not the current request]\n" + quoted[:400]
    # Calendar evidence shares the configured body budget rather than expanding
    # the privacy/token allowance. Limit individual attachments and their count.
    calendar = "\n".join(data[:1200] for data in raw.calendar_data[:2])
    calendar = "\n".join(line for line in calendar.splitlines() if line.startswith(
        ("SUMMARY", "DESCRIPTION", "DTSTART", "DTEND", "METHOD", "STATUS")))[:400]
    limit = max(0, max_body_chars)
    context = ("\n[Calendar context]\n" + calendar) if calendar else ""
    context = context[:min(len(context), limit // 2)]
    budget = limit - len(context)
    if len(body) > budget:
        marker = "\n[...truncated middle...]\n"
        if budget > len(marker) + 40:
            # Select at most two relevant windows before spending the rest on
            # the head/tail. This catches a request buried after HTML boilerplate.
            windows = []
            for match in re.finditer(
                r"interview|phone screen|received your application|application received|assessment|other candidates",
                body, re.I,
            ):
                start = max(0, match.start() - 80)
                if not windows or start > windows[-1][1]:
                    windows.append((start, min(len(body), match.end() + 160)))
                if len(windows) == 2:
                    break
            evidence = "\n".join(body[a:b] for a, b in windows)[:budget // 2]
            remaining = budget - len(marker) - len(evidence)
            head = remaining * 2 // 3
            tail = remaining - head
            body = body[:head] + marker + evidence + body[-tail:]
        else:
            marker = "[...truncated]"[:budget]
            body = body[:budget - len(marker)] + marker
    body += context
    return NormalizedMessage(
        account_id=account_id,
        account_label=account_label,
        message_id=raw.message_id,
        uid=raw.uid,
        folder=raw.folder,
        from_addr=raw.from_addr,
        from_name=raw.from_name,
        subject=raw.subject,
        date_utc=raw.date_utc,
        body=body,
        original_html=raw.original_html or (
            raw.text if _HTML_HINT.search(raw.text or "")
            else '<div style="white-space:pre-wrap">' + html.escape(raw.text or "") + "</div>"
        ),
        provider_url=raw.provider_url,
        calendar_data=raw.calendar_data,
        thread_id=raw.thread_id,
        references=raw.references,
        interview_text=_strip_footer(_strip_quotes(_html_to_text(raw.text) if _HTML_HINT.search(raw.text or "") else (raw.text or "")))[:24000],
    )
