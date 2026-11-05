"""Application factory and shared configuration."""
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask

from .auth import register_auth
from .routes import register_routes

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        GOOGLE_CLIENT_ID=os.environ.get('GOOGLE_CLIENT_ID'),
        GOOGLE_CLIENT_SECRET=os.environ.get('GOOGLE_CLIENT_SECRET'),
        PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL', 'http://localhost:5001').rstrip('/'),
        ALLOWED_EMAILS=os.environ.get('ALLOWED_EMAILS', ''),
        ALLOWED_DOMAIN=os.environ.get('ALLOWED_DOMAIN', '').lower(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24*30),
    )
    if config:
        app.config.update(config)
    for key in ('SECRET_KEY', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'):
        if not app.config.get(key):
            raise RuntimeError(f'Set {key} before starting the server (see README.md).')
    base = urlsplit(app.config['PUBLIC_BASE_URL'])
    if (not base.hostname or base.path or base.query or base.fragment or base.username
            or base.scheme not in ('http', 'https')
            or (base.scheme == 'http' and base.hostname not in ('localhost', '127.0.0.1'))):
        raise RuntimeError('PUBLIC_BASE_URL must be an HTTPS origin, or HTTP localhost for development.')
    app.config['SESSION_COOKIE_SECURE'] = base.scheme == 'https'
    app.config.setdefault('DATA_DIR', ROOT / 'data')
    register_auth(app)
    register_routes(app)
    return app
