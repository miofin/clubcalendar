import yaml
import logging
import imaplib
import email


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

me, mypwd = load_credentials('credentials.yaml')


mail = connect_to_gmail_imap(me, mypwd)

status, messages = mail.search(None, 'TO "Re-INNformer@princeton.edu"')

for num in messages[0].split()[::-1]:
    _, msg = mail.fetch(num, "(RFC822)")

    message = email.message_from_bytes(msg[0][1])

    subject_header = message['Subject']
    decoded_subject = email.header.decode_header(subject_header)
    subject = decoded_subject[0][0]

    print("Subject: ", subject)
    print("From: ", message["From"])
    print("Date: ", message["Date"])



print(messages)