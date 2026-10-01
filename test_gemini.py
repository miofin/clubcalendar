from google import genai
import os
import json

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

email_subject = "First Meeting 10/1!!!"

email_body = """
Calling all birders!

The Princeton Birding Society's first meeting of the year will take place
on Thursday, October 1, from 4:30-5:30 in Frist 302. We will go over the
basics of birding, introduce the officers, and announce some future events!

See you all soon!

PBS 🐦
"""

prompt = f"""
You extract club meeting information from university club emails.

Today's date is September 28, 2026.

Given the email subject and body below, extract the club name and meeting
date/time.

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
{email_subject}

EMAIL BODY:
{email_body}
"""

interaction = client.interactions.create(
    model="gemini-3.8-flash",
    input=prompt
)

print(interaction.output_text)
