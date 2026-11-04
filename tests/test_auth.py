import unittest
from unittest.mock import patch

from authlib.integrations.base_client.errors import OAuthError
from app import create_app


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(dict(TESTING=True, SECRET_KEY='test-secret',
                                  GOOGLE_CLIENT_ID='test-client', GOOGLE_CLIENT_SECRET='test-secret',
                                  PUBLIC_BASE_URL='https://calendar.example', ALLOWED_EMAILS='', ALLOWED_DOMAIN=''))
        self.client = self.app.test_client()
        self.google = self.app.extensions['authlib.integrations.flask_client'].create_client('google')

    def user(self, **overrides):
        return dict(sub='123', email='person@example.com', email_verified=True, **overrides)

    def login(self, user=None):
        with patch.object(self.google, 'authorize_access_token', return_value={'userinfo': user or self.user()}):
            return self.client.get('/auth/callback')

    def test_anonymous_data_and_page_blocked(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/index.html').status_code, 302)
        response = self.client.get('/meetings.json')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_private_files_never_served(self):
        for path in ('/emails.json', '/new_emails.json', '/credentials.yaml', '/.env', '/app.py'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.login()
        self.assertEqual(self.client.get('/emails.json').status_code, 404)

    def test_login_and_logout(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertIn('Secure', response.headers['Set-Cookie'])
        self.assertEqual(self.client.get('/').status_code, 200)
        with self.client.get('/meetings.json') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post('/logout').status_code, 400)
        with self.client.session_transaction() as session:
            csrf = session['csrf']
            self.assertNotIn('access_token', session)
        self.assertEqual(self.client.post('/logout', data={'csrf': csrf}).status_code, 302)
        self.assertEqual(self.client.get('/meetings.json').status_code, 401)

    def test_failed_oauth_and_unverified_account(self):
        with patch.object(self.google, 'authorize_access_token', side_effect=OAuthError()):
            self.assertEqual(self.client.get('/auth/callback').status_code, 400)
        user = self.user()
        user['email_verified'] = False
        self.assertEqual(self.login(user).status_code, 403)
        self.assertEqual(self.client.get('/meetings.json').status_code, 401)

    def test_domain_requires_google_hd_claim(self):
        self.app.config['ALLOWED_DOMAIN'] = 'example.com'
        self.assertEqual(self.login().status_code, 403)
        self.assertEqual(self.login(self.user(hd='example.com')).status_code, 302)

    def test_login_uses_callback_host_before_creating_state(self):
        with patch.object(self.google, 'authorize_redirect') as authorize:
            response = self.client.get('/auth/google', base_url='http://127.0.0.1:5001')
            self.assertEqual(response.location, 'https://calendar.example/auth/google')
            authorize.assert_not_called()

    def test_pending_login_survives_visiting_calendar_and_new_login(self):
        origin = 'https://calendar.example'
        with self.client.session_transaction(base_url=origin) as session:
            session['_state_google_first'] = {'data': {'nonce': 'first'}}
        self.client.get('/', base_url=origin)
        with patch.object(self.google, 'authorize_redirect', return_value='Google redirect'):
            response = self.client.get('/auth/google', base_url=origin)
            self.assertEqual(response.status_code, 200)
        with self.client.session_transaction(base_url=origin) as session:
            self.assertIn('_state_google_first', session)

    def test_first_successful_callback_opens_calendar(self):
        with patch.object(self.google, 'authorize_access_token', return_value={'userinfo': self.user()}):
            response = self.client.get('/auth/callback', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Signed in as person@example.com', response.data)
        self.assertNotIn(b'Sign-in failed', response.data)

    def test_email_allowlist(self):
        app = create_app(dict(TESTING=True, SECRET_KEY='test', GOOGLE_CLIENT_ID='id',
                             GOOGLE_CLIENT_SECRET='secret', ALLOWED_EMAILS='owner@example.com'))
        google = app.extensions['authlib.integrations.flask_client'].create_client('google')
        with patch.object(google, 'authorize_access_token', return_value={'userinfo': self.user()}):
            self.assertEqual(app.test_client().get('/auth/callback').status_code, 403)


if __name__ == '__main__':
    unittest.main()
