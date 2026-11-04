"""Authenticated web server; email ingestion remains a separate local job."""
import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from jinja2 import ChoiceLoader, FileSystemLoader
from joserfc.errors import JoseError
from requests.exceptions import RequestException
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session

ROOT = Path(__file__).resolve().parent


def create_app(config=None):
    app = Flask(__name__, static_folder=None, template_folder=str(ROOT / 'templates'))
    app.jinja_loader = ChoiceLoader([FileSystemLoader(str(ROOT / 'templates')), FileSystemLoader(str(ROOT))])
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        GOOGLE_CLIENT_ID=os.environ.get('GOOGLE_CLIENT_ID'),
        GOOGLE_CLIENT_SECRET=os.environ.get('GOOGLE_CLIENT_SECRET'),
        PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL', 'http://localhost:5000').rstrip('/'),
        ALLOWED_EMAILS=os.environ.get('ALLOWED_EMAILS', ''),
        ALLOWED_DOMAIN=os.environ.get('ALLOWED_DOMAIN', '').lower(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
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
    allowed_emails = {e.strip().lower() for e in app.config['ALLOWED_EMAILS'].split(',') if e.strip()}

    oauth = OAuth(app)
    google = oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
    )

    def permitted(user):
        return (bool(user.get('sub')) and user.get('email_verified') is True
                and bool(user.get('email'))
                and (not allowed_emails or user['email'].lower() in allowed_emails)
                and (not app.config['ALLOWED_DOMAIN']
                     or user.get('hd', '').lower() == app.config['ALLOWED_DOMAIN']))

    @app.before_request
    def protect():
        if request.endpoint in ('index', 'meetings'):
            if not permitted(session.get('user', {})):
                # Keep pending OAuth state intact if another tab opens the calendar.
                session.pop('user', None)
                if request.endpoint == 'meetings':
                    return jsonify(error='Sign in required'), 401
                return redirect('/login')

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if app.config['SESSION_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/login')
    def login():
        return render_template('login.html')

    @app.get('/auth/google')
    def start_login():
        # Establish OAuth state on the same host that receives Google's callback.
        # localhost and 127.0.0.1 have separate cookies, even on the same machine.
        if request.host.lower() != base.netloc.lower():
            return redirect(app.config['PUBLIC_BASE_URL'] + '/auth/google')
        # Authlib tracks each flow by state; do not erase other in-flight logins.
        session.pop('user', None)
        session.pop('csrf', None)
        return google.authorize_redirect(app.config['PUBLIC_BASE_URL'] + '/auth/callback',
                                         nonce=secrets.token_urlsafe(32))

    @app.get('/auth/callback')
    def callback():
        try:
            token = google.authorize_access_token()
        except (OAuthError, JoseError, RequestException, ValueError) as error:
            # Only log the exception class: messages may contain provider secrets.
            app.logger.warning('Google sign-in failed (%s)', type(error).__name__)
            session.pop('user', None)
            return render_template('login.html', error='Sign-in failed. Please try again.'), 400
        user = token.get('userinfo', {})
        session.clear()
        if not permitted(user):
            return render_template('login.html', error='This Google account does not have access.'), 403
        # Never persist Google access/refresh tokens in the browser session.
        session['user'] = {k: user[k] for k in ('sub', 'email', 'email_verified', 'hd') if k in user}
        session['csrf'] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect('/')

    @app.get('/')
    @app.get('/index.html')
    def index():
        return render_template('index.html', email=session['user']['email'], csrf=session['csrf'])

    @app.get('/meetings.json')
    def meetings():
        return send_file(ROOT / 'meetings.json', mimetype='application/json')

    @app.post('/logout')
    def logout():
        expected = session.get('csrf')
        if not expected or not secrets.compare_digest(request.form.get('csrf', ''), expected):
            abort(400)
        session.clear()
        return redirect('/login')

    return app
