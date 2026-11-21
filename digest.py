
import os
import re
import imaplib
import smtplib
import email
from email.header import decode_header, make_header
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html import unescape

USER = os.environ["YAHOO_EMAIL"]
PASSWORD = os.environ["YAHOO_APP_PASSWORD"]
DESTINATION = os.environ["DIGEST_TO"]
LOCAL_TZ = ZoneInfo("Asia/Shanghai")

KEYWORDS = [
    "urgent", "action required", "deadline",
    "approval", "confirm", "invoice",
    "payment", "meeting", "contract",
    "asap", "重要", "紧急", "审批",
    "确认", "付款", "合同", "截止"
]

def decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)

def get_body(message):
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() != "text/plain":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        try:
            raw = part.get_payload(decode=True)
            if raw:
                charset = part.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except Exception:
            continue
    return ""

def clean(text):
    text = unescape(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def priority(subject, body):
    combined = (subject + " " + body[:1500]).lower()
    return sum(1 for word in KEYWORDS if word in combined)

now = datetime.now(timezone.utc)
start = now - timedelta(hours=24)
messages = []

with imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993) as mailbox:
    mailbox.login(USER, PASSWORD)
    mailbox.select("INBOX", readonly=Falseprocessed_ids)
    status, data = mailbox.search(
        None, "SINCE", start.strftime("%d-%b-%Y")
    )
    if status != "OK":
        raise RuntimeError("Unable to search Yahoo inbox")

    for message_id in data[0].split():
        status, result = mailbox.fetch(message_id, "(BODY.PEEK[])")
        if status != "OK":
            continue
        raw = next(
            (item[1] for item in result if isinstance(item, tuple)),
            None
        )
        if not raw:
            continue

        msg = email.message_from_bytes(raw)
        received = email.utils.parsedate_to_datetime(msg["Date"])
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        if not start <= received.astimezone(timezone.utc) <= now:
            continue

        subject = decode(msg["Subject"]) or "(No subject)"
        sender = decode(msg["From"])
        body = clean(get_body(msg))
        messages.append({
            "sender": sender,
            "subject": subject,
            "preview": body[:240] or "No plain-text preview",
            "score": priority(subject, body),
            "received": received
        })
        processed_ids.append(message_id)

important = sorted(
    [m for m in messages if m["score"] > 0],
    key=lambda m: (-m["score"], -m["received"].timestamp())
)
other = sorted(
    [m for m in messages if m["score"] == 0],
    key=lambda m: -m["received"].timestamp()
)

def format_item(item):
    return (
        f"From: {item['sender']}\n"
        f"Subject: {item['subject']}\n"
        f"Preview: {item['preview']}\n"
    )

today = now.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
sections = [
    f"YAHOO DAILY DIGEST — {today}",
    f"Total new messages: {len(messages)}",
    f"Potentially important: {len(important)}",
    "\nIMPORTANT / ACTION CANDIDATES\n",
]

sections.extend(format_item(m) for m in important[:15])
sections.append("\nOTHER EMAILS\n")
sections.extend(format_item(m) for m in other[:20])
sections.append(
    "\nNote: Importance is based on keywords, "
    "not AI understanding. Review original emails "
    "before taking action."
)

digest = "\n".join(sections)

outgoing = EmailMessage()
outgoing["From"] = USER
outgoing["To"] = DESTINATION
outgoing["Subject"] = f"Yahoo Daily Digest — {today}"
outgoing.set_content(digest)

with smtplib.SMTP_SSL("smtp.mail.yahoo.com", 465) as smtp:
    smtp.login(USER, PASSWORD)
    smtp.send_message(outgoing)
# Mark included emails as read only after
# the digest has been successfully sent.

with imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993) as mailbox:
    mailbox.login(USER, PASSWORD)
    mailbox.select("INBOX", readonly=False)

    for message_id in processed_ids:
        status, _ = mailbox.store(
            message_id, "+FLAGS", r"(\Seen)"
        )
        if status != "OK":
            print(f"Failed to mark message {message_id!r} as read")
print(f"Digest sent successfully; {len(messages)} messages reviewed.")
