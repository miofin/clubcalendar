from google import genai
import os
import json


client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

with open("emails.json", "r") as file:
    emails = json.load(file)

print(emails)

for email in emails:
    subject=email["Subject"]
    sender = email["From"]
    send_date = email["Date"]
    body = email["Body"]

    prompt = f"""
    You extract club meeting information from university club emails.

    Given the email subject and body below, extract the club name and meeting
    date/time

    Return ONLY valid JSON in exactly this format:

    {{
        "club_name": "...",
        "date": "YYYY-MM-DD",
        "start_time": "HH:MM",
        "end_time": "HH:MM"
    }}

    Use 24-hour time.

    If the email does not contain a specific meeting, return:

    {{
        "club_name": null,
        "date": null,
        "start_time": null,
        "end_time": null
    }}

    EMAIL SUBJECT:
    {subject}

    EMAIL BODY:
    {body}

    SEND DATE:
    {send_date}

    SENDER:
    {sender}
    """

    interaction = client.interactions.create(
        model="gemini-3.6-flash",
        input=prompt
    )
    
    print(interaction.output_text)

