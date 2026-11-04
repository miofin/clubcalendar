"""Authenticated calendar page and meeting data routes."""
from pathlib import Path

from flask import render_template, send_file, session


def register_routes(app):
    @app.get('/')
    @app.get('/index.html')
    def index():
        return render_template('index.html', email=session['user']['email'], csrf=session['csrf'])

    @app.get('/meetings.json')
    def meetings():
        return send_file(Path(app.config['DATA_DIR']) / 'meetings.json', mimetype='application/json')

