import yaml
import logging
import imaplib
import email
import re
import json
import html


imap_url = 'imap.gmail.com'
mail = imaplib.IMAP4_SSL(imap_url)


def load_credentials(filepath):
    try:
        with open(filepath, 'r') as file:
            credentials = yaml.safe_load(file)
            user = credentials['user']
            password = credentials['password']
            return user, password
    except Exception as e:
        logging.error("Failed to load credentials: {}".format(e))
        raise

def connect_to_gmail_imap(user, password):
    try:
        mail.login(user, password)
        mail.select('inbox')  # Connect to the inbox.
        return mail
    except Exception as e:
        logging.error("Connection failed: {}".format(e))
        raise

def get_email_body(msg):
  if msg.is_multipart():
    for part in msg.walk():
      content_type = part.get_content_type()
      content_disposition = str(part.get("Content-Disposition"))

      # Skip attachments
      if "attachment" in content_disposition:
        continue

      if content_type == "text/plain":
        try:
          return part.get_payload(decode=True).decode()
        except Exception:
          pass
      elif content_type == "text/html":
        try:
          return part.get_payload(decode=True).decode()
        except Exception:
          pass
  else:
    return msg.get_payload(decode=True).decode()

def get_plain_body(msg):
    body = get_email_body(msg)
    if body is None:
        return ""
    return html.unescape(re.sub(r'<.*?>', '', body))


me, mypwd = load_credentials('credentials.yaml')
mail = connect_to_gmail_imap(me, mypwd)
status, messages = mail.search(None, 'TO "Re-INNformer@princeton.edu"')#eventually also add "UNSEEN"


message_list = []

for num in messages[0].split()[::-1]:
    _, msg = mail.fetch(num, "(RFC822)")

    message = email.message_from_bytes(msg[0][1])

    subject_header = message['Subject']
    subject = email.header.make_header(email.header.decode_header(subject_header or ""))
    subject = str(subject)

    message_list.append({"Subject": subject, "From": str(message["From"]), "Date": str(message["Date"]), "Body": str(get_plain_body(message))})

print(message_list)

with open("emails.json", "w", encoding="utf-8") as file:
    json.dump(message_list, file, indent=4)
