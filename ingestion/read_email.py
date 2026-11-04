import email
import html
import imaplib
import json
import logging
import os
import re
from collections import defaultdict
from email import policy
from pathlib import Path

import yaml

IMAP_URL = "imap.gmail.com"
SEARCH_CRITERIA = '(UNSEEN TO "Re-INNformer@princeton.edu")'
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_FILE = DATA_DIR / "emails.json"
OTHER_OUTPUT_FILE = DATA_DIR / "new_emails.json"
BATCH_SIZE = 100

TAG_RE = re.compile(r"<(script|style).*?</\1>|<.*?>", re.DOTALL | re.IGNORECASE)
WS_RE = re.compile(r"\s+")  # <-- add this line
TOKEN_RE = re.compile(rb'\(|\)|"((?:[^"\\]|\\.)*)"|[^\s()"]+')
UID_RE = re.compile(rb"UID (\d+)")
SECTION_RE = re.compile(rb"BODY\[(.*?)\]")


def load_credentials(filepath):
    try:
        with open(filepath, "r") as f:
            creds = yaml.safe_load(f)
        return creds["user"], creds["password"]
    except Exception as e:
        logging.error("Failed to load credentials: %s", e)
        raise


def connect(user, password):
    mail = imaplib.IMAP4_SSL(IMAP_URL)
    mail.login(user, password)
    mail.select("inbox")  # read-write, so we can set \Seen later
    return mail


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------- BODYSTRUCTURE

def parse_bodystructure(raw):
    """Parse the parenthesised BODYSTRUCTURE into nested Python lists."""
    stack = [[]]
    for m in TOKEN_RE.finditer(raw):
        tok = m.group(0)
        if tok == b"(":
            stack.append([])
        elif tok == b")":
            done = stack.pop()
            stack[-1].append(done)
            if len(stack) == 1:  # finished the top-level structure
                return stack[0][0]
        elif tok.startswith(b'"'):
            stack[-1].append(m.group(1).decode("latin-1"))
        else:
            s = tok.decode("latin-1")
            stack[-1].append(None if s.upper() == "NIL" else s)
    raise ValueError("Unbalanced BODYSTRUCTURE")


def is_attachment(part):
    for el in part[7:]:
        if isinstance(el, list) and el and isinstance(el[0], str) \
                and el[0].lower() == "attachment":
            return True
    return False


def collect_text_parts(bs, num, out):
    if isinstance(bs[0], list):  # multipart
        for i, child in enumerate(bs, 1):
            if not isinstance(child, list):
                break
            collect_text_parts(child, f"{num}.{i}" if num else str(i), out)
    elif bs[0] and bs[0].lower() == "text" and not is_attachment(bs):
        out.append((num or "1", bs[1].lower()))


def choose_part(bs):
    """Prefer HTML so we can retain markup and derive the plain-text body."""
    parts = []
    collect_text_parts(bs, "", parts)
    for wanted in ("html", "plain"):
        for num, sub in parts:
            if sub == wanted:
                return num
    return None


def find_body_parts(mail, uids):
    """Map uid -> part number to download (or None), fetching structure only."""
    result = {}
    for batch in chunks(uids, 200):
        _, data = mail.uid("fetch", b",".join(batch), "(UID BODYSTRUCTURE)")
        for item in data:
            raw = item[0] if isinstance(item, tuple) else item
            if not isinstance(raw, bytes):
                continue
            uid_m = UID_RE.search(raw)
            idx = raw.find(b"BODYSTRUCTURE ")
            if not uid_m or idx < 0:
                continue
            try:
                bs = parse_bodystructure(raw[idx + len(b"BODYSTRUCTURE "):])
                result[uid_m.group(1)] = choose_part(bs)
            except Exception as e:
                logging.warning("Could not parse structure for UID %s: %s",
                                uid_m.group(1).decode(), e)
                result[uid_m.group(1)] = None
    return result


# ---------------------------------------------------------------- Fetching text

def fetch_records(mail, uids, part):
    """Fetch headers (+ one text part if given) for uids; returns {uid: sections}."""
    items = "UID BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)]"
    if part:
        items += f" BODY.PEEK[{part}.MIME] BODY.PEEK[{part}]"
    _, data = mail.uid("fetch", b",".join(uids), f"({items})")

    records = {}
    current = None
    for item in data:
        if isinstance(item, tuple):
            prefix, literal = item
            if re.match(rb"\d+ \(", prefix):  # start of a new message
                current = {}
            uid_m = UID_RE.search(prefix)
            if uid_m:
                current["uid"] = uid_m.group(1)
            sec_m = SECTION_RE.search(prefix)
            if sec_m:
                sec = sec_m.group(1).decode()
                if sec.upper().startswith("HEADER"):
                    current["header"] = literal
                elif sec.upper().endswith(".MIME"):
                    current["mime"] = literal
                else:
                    current["body"] = literal
        elif isinstance(item, bytes) and current is not None:
            uid_m = UID_RE.search(item)
            if uid_m:
                current["uid"] = uid_m.group(1)
        if current is not None and "uid" in current:
            records[current["uid"]] = current
    return records


def to_plain_text(rec):
    body = rec.get("body")
    if not body:
        return ""
    try:
        msg = email.message_from_bytes(rec.get("mime", b"") + body,
                                       policy=policy.default)
        text = msg.get_content()
        # Replace tags with a space so adjacent text doesn't get fused
        text = html.unescape(TAG_RE.sub(" ", text))
        # Collapse newlines, tabs, nbsp, and repeated spaces into a single space
        return WS_RE.sub(" ", text).strip()
    except Exception as e:
        logging.warning("Failed to decode body for UID %s: %s",
                        rec["uid"].decode(), e)
        return ""

def build_entry(rec):
    hdr = email.message_from_bytes(rec.get("header", b""), policy=policy.default)
    body = email.message_from_bytes(rec.get("mime", b"") + rec.get("body", b""), policy=policy.default)
    return {
        "Subject": str(hdr["Subject"] or ""),
        "From": str(hdr["From"] or ""),
        "Date": str(hdr["Date"] or ""),
        "Body": to_plain_text(rec),
        "html": body.get_content() if body.get_content_type() == "text/html" else "",
    }


# ---------------------------------------------------------------------- Main

def main():
    user, password = load_credentials(PROJECT_DIR / "credentials.yaml")
    mail = connect(user, password)

    _, found = mail.uid("search", None, SEARCH_CRITERIA)
    uids = found[0].split()
    if not uids:
        print("No new emails.")
        with open(OTHER_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)
        return

    # 1. Learn each message's layout (tiny), pick one text part per message.
    part_for_uid = find_body_parts(mail, uids)

    # 2. Group messages by part number so each group is one batched fetch.
    groups = defaultdict(list)
    for uid in uids:
        groups[part_for_uid.get(uid)].append(uid)

    new_entries = []  # (uid_int, entry)
    processed = []
    for part, group_uids in groups.items():
        for batch in chunks(group_uids, BATCH_SIZE):
            for uid, rec in fetch_records(mail, batch, part).items():
                new_entries.append((int(uid), build_entry(rec)))
                processed.append(uid)

    new_entries.sort(key=lambda x: x[0], reverse=True)  # newest first
    new_messages = [entry for _, entry in new_entries]

    print(f'adding {len(new_messages)} new emails')

    # 3. Append to existing output so repeat runs don't overwrite earlier ones.
    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            logging.warning("Could not read existing %s (%s); starting fresh.",
                            OUTPUT_FILE, e)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing + new_messages, f, indent=4)
    
    if os.path.exists(OTHER_OUTPUT_FILE):
        try:
            with open(OTHER_OUTPUT_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            logging.warning("Could not read existing %s (%s); starting fresh.",
                            OTHER_OUTPUT_FILE, e)

    with open(OTHER_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_messages, f, indent=4)

    # 4. Only after the file is safely written, mark the messages as read.
    for batch in chunks(processed, 200):
        mail.uid("store", b",".join(batch), "+FLAGS", r"(\Seen)")

    mail.close()
    mail.logout()
    print(f"Saved {len(new_messages)} new emails to {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()