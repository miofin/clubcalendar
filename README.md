# Club Calendar

The Flask server requires Google sign-in for the calendar and `meetings.json`.
Email fetching/parsing stays a separate job using your existing inbox credentials.
Visitors sign in to view the shared calendar; their inboxes are not accessed.

## Google setup

1. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview) in your Google Cloud project. Configure Branding, Audience, and the OAuth consent screen. For an external app in Testing, add your Google account and other testers under Audience. Publish the app when ready for general access.
2. Create an OAuth client with application type **Web application** under Clients.
3. Add this exact authorized redirect URI for local development: `http://localhost:5000/auth/callback`.
4. Add your production redirect URI too: `https://YOUR-DOMAIN/auth/callback`.
5. Copy the client ID and client secret into the environment settings below. Do not commit them. Only `openid email profile` scopes are requested; no Gmail permissions are requested.

## Run locally

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Edit `.env`: set `SECRET_KEY` to the generated random value and fill in the Google client ID and secret. Then run:

```sh
flask --app 'app:create_app()' run --port 5000
```

Open `http://localhost:5000`. Flask loads `.env` via python-dotenv.

By default **any verified Google account** can view the shared meetings. To restrict access, set `ALLOWED_EMAILS` to a comma-separated list and/or `ALLOWED_DOMAIN` to a Google Workspace domain (for example `princeton.edu`). The domain is checked against Google's verified `hd` claim; it must be a Workspace organization. If both settings are present, both must match. Restart the server after changing settings.

## Public hosting

Use a Python web host/container with HTTPS, not GitHub Pages or another static host.

- Install command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT 'app:create_app()'` (set `PORT=8000` if your host does not provide it).
- Set `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `PUBLIC_BASE_URL=https://YOUR-DOMAIN` in the host's environment. Use the same persistent secret across workers and redeploys. Gunicorn does not automatically load `.env`.
- Match `PUBLIC_BASE_URL` exactly to Google's authorized redirect URI, appending `/auth/callback` in Google. The fixed configured URL avoids trusting proxy/Host headers for the OAuth callback.
- Deploy `meetings.json` alongside the app. Your existing `update_meetings.py` pipeline can continue regenerating and pushing it; configure your host to redeploy on those commits or update the file on persistent storage.
- Do not configure a web server/CDN to serve the repository or JSON files directly. Only forward requests to Flask. The server exposes an explicit set of routes and never serves `emails.json`, `new_emails.json`, or `credentials.yaml`.
- Keep the repository private if its tracked meeting history is private; app authentication does not protect files independently published through GitHub or static hosting.

Sessions expire after eight hours and use signed, HttpOnly, SameSite cookies, with Secure enabled for HTTPS. Logout uses a CSRF-protected POST. Google state, nonce, PKCE, and ID-token verification are handled by Authlib's OpenID Connect integration.

## Verify

```sh
python -m unittest discover -s tests -v
```

Tests mock Google token exchange; a real Google round trip requires your client credentials and registered redirect URL.
