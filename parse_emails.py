import json
from find_date import find_first_date
from find_time import find_first_time


with open("new_emails.json", "r") as file:
    emails = json.load(file)

try:
    with open("meetings.json", "r") as file:
        meetings = json.load(file)
        print('read meetings')
except (FileNotFoundError, json.JSONDecodeError):
    meetings = []


for email in emails:
    subject=email["Subject"]
    sender = email["From"]
    send_date = email["Date"]
    body = email["Body"]

    club = sender[:-23]
    date = find_first_date(body, send_date)
    time = find_first_time(body)
    

    if date and time and (club != "Hoagie Mail"):
        date_string = "2026-"+str(date.month)+"-"+str(date.day)
        time_string = str(time.hour)+":"+str(time.minute)
        duplicate = False
        for meeting in meetings:
            if meeting["club_name"] == club and meeting["date"] == date_string and meeting["start_time"]==time_string:
                duplicate = True
                break
        if duplicate:
            continue
        meetings.append({
        "club_name": club,
        "date": date_string,
        "start_time": str(time.hour)+":"+str(time.minute),
        "subject": subject
    })

with open("meetings.json", "w") as file:
    json.dump(meetings, file, indent=4)