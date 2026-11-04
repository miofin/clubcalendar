"""Check asset exposure and ingestion paths after reorganizing the project."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from ingestion import parse_emails, read_email, update_meetings


class StructureTests(unittest.TestCase):
    def test_only_public_assets_are_served(self):
        app = create_app(dict(TESTING=True, SECRET_KEY='test', GOOGLE_CLIENT_ID='test',
                             GOOGLE_CLIENT_SECRET='test'))
        client = app.test_client()
        for path in ('/static/css/style.css', '/static/js/calendar.js'):
            with client.get(path) as response:
                self.assertEqual(response.status_code, 200)
        for path in ('/data/meetings.json', '/data/emails.json', '/data/new_emails.json',
                     '/app/templates/index.html', '/static/../data/meetings.json'):
            self.assertEqual(client.get(path).status_code, 404)

    def test_ingestion_paths_are_project_relative(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(read_email.OUTPUT_FILE, root / 'data/emails.json')
        self.assertEqual(read_email.OTHER_OUTPUT_FILE, root / 'data/new_emails.json')
        self.assertEqual(update_meetings.PROJECT_DIR, root)

    def test_parser_uses_data_directory_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'data'
            data.mkdir()
            (data / 'new_emails.json').write_text('[]')
            (data / 'meetings.json').write_text('[{"club_name": "Existing club"}]')
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(parse_emails, 'DATA_DIR', data):
                    parse_emails.main()
            finally:
                os.chdir(previous)
            self.assertEqual(json.loads((data / 'meetings.json').read_text()),
                             [{'club_name': 'Existing club'}])

    def test_update_runs_modules_from_project_root(self):
        with patch.object(update_meetings, 'run_command') as run:
            update_meetings.main()
        self.assertEqual([call.args[0][1:] for call in run.call_args_list],
                         [['-m', 'ingestion.read_email'], ['-m', 'ingestion.parse_emails']])
