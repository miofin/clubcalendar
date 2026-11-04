"""Google OpenID Connect, account restrictions, and session handling."""
import secrets
from urllib.parse import urlsplit

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import abort, jsonify, redirect, render_template, request, session
from joserfc.errors import JoseError
from requests.exceptions import RequestException


def register_auth(app):
    base = urlsplit(app.config['PUBLIC_BASE_URL'])
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

    @app.post('/logout')
    def logout():
        expected = session.get('csrf')
        if not expected or not secrets.compare_digest(request.form.get('csrf', ''), expected):
            abort(400)
        session.clear()
        return redirect('/login')

