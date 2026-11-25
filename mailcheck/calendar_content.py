"""Calendar-specific bounded context, independent of email classification limits."""
import re

VERSION='2'
DESCRIPTION_LIMIT=12000
SOURCE_LIMIT=16000
_DETAIL=re.compile(r'\b(?:interview\w*|employer|company|role|position|candidate|hiring|recruit\w*|assessment|engineer|developer)\b',re.I)
_BOILERPLATE=re.compile(r'^\s*(?:join (?:the |a )?(?:meeting|zoom|microsoft|teams)|meeting id\b|passcode\b|dial.in\b|need help\b|microsoft teams\b|zoom meeting\b)',re.I)


def description(value):
    text=(value or '')[:SOURCE_LIMIT]
    if len(text)<=DESCRIPTION_LIMIT:return text
    chunks=[line[offset:offset+1000] for line in text.splitlines() for offset in range(0,len(line),1000)]
    def priority(index):
        value=chunks[index]
        return (0 if _DETAIL.search(value) else 2 if _BOILERPLATE.search(value) else 1,index)
    selected={}
    remaining=DESCRIPTION_LIMIT
    for index in sorted(range(len(chunks)),key=priority):
        if remaining<=1:break
        selected[index]=chunks[index][:remaining-1]
        remaining-=len(selected[index])+1
    # Restore source order so selecting details does not change their chronology.
    return '\n'.join(selected[index] for index in sorted(selected))
