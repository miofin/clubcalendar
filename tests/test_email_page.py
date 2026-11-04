import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from app import create_app


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class EmailPageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.markup = '<h2>Meeting details</h2><script>alert(1)</script><img src="https://example.com/tracker">'
        (self.data / 'meetings.json').write_text(json.dumps([
            {'club_name': '<b>Club</b>', 'subject': 'Invitation', 'html': self.markup},
            {'club_name': 'Older meeting'},
        ]))
        self.app = create_app(dict(TESTING=True, SECRET_KEY='test', GOOGLE_CLIENT_ID='test',
                                  GOOGLE_CLIENT_SECRET='test', DATA_DIR=self.data,
                                  PUBLIC_BASE_URL='http://localhost:5001',
                                  ALLOWED_DOMAIN='', ALLOWED_EMAILS=''))
        self.client = self.app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session['user'] = dict(sub='123', email='user@example.com', email_verified=True)

    def test_email_requires_sign_in(self):
        response = self.client.get('/meetings/0')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/login')

    def test_html_is_isolated_and_remote_resources_blocked(self):
        self.sign_in()
        response = self.client.get('/meetings/0')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        elements = Elements(html)
        iframe = next(attrs for tag, attrs in elements.tags if tag == 'iframe')
        self.assertEqual(iframe['sandbox'], '')
        self.assertEqual(iframe['referrerpolicy'], 'no-referrer')
        self.assertIn(self.markup, iframe['srcdoc'])
        self.assertIn("default-src 'none'", iframe['srcdoc'])
        self.assertIn('img-src data:', iframe['srcdoc'])
        self.assertLess(iframe['srcdoc'].index('Content-Security-Policy'), iframe['srcdoc'].index(self.markup))
        self.assertNotIn('script', [tag for tag, attrs in elements.tags])
        self.assertIn('&lt;b&gt;Club&lt;/b&gt;', html)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_older_email_and_invalid_ids(self):
        self.sign_in()
        response = self.client.get('/meetings/1')
        self.assertIn('Email content isn’t available.', response.get_data(as_text=True))
        for path in ('/meetings/2', '/meetings/-1', '/meetings/not-a-number'):
            self.assertEqual(self.client.get(path).status_code, 404)
