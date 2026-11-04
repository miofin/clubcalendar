"""Authenticated calendar page and meeting data routes."""
import json
from pathlib import Path

from flask import abort, render_template, send_file, session

from .email_html import links_in_new_tabs


def register_routes(app):
    @app.get('/')
    @app.get('/index.html')
    def index():
        return render_template('index.html', email=session['user']['email'], csrf=session['csrf'])

    @app.get('/meetings.json')
    def meetings():
        return send_file(Path(app.config['DATA_DIR']) / 'meetings.json', mimetype='application/json')


    @app.get('/meetings/<int:meeting_id>')
    def meeting_email(meeting_id):
        with (Path(app.config['DATA_DIR']) / 'meetings.json').open(encoding='utf-8') as file:
            records = json.load(file)
        if not isinstance(records, list) or meeting_id >= len(records):
            abort(404)
        meeting = records[meeting_id]
        if not isinstance(meeting, dict):
            abort(404)
        content = meeting.get('html')
        # The policy precedes all untrusted markup; srcdoc stays autoescaped.
        email_document = None
        if isinstance(content, str) and content.strip():
            email_document = (
                '<!doctype html><html><head><meta charset="utf-8">'
                '<meta http-equiv="Content-Security-Policy" content="'
                "default-src 'none'; style-src 'unsafe-inline'; img-src data: https: http:; "
                "base-uri 'none'; form-action 'none'"
                '"><meta name="referrer" content="no-referrer">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<style>html{color-scheme:light}body{margin:0;padding:0;'
                'font:14px/1.5 Arial,sans-serif;color:#202124;background:#fff}'
                'img{max-width:100%;height:auto}</style></head><body>'
                + links_in_new_tabs(content) + '</body></html>'
            )
        return render_template('email.html', meeting=meeting, email_document=email_document)
