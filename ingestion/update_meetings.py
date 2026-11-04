import subprocess
import sys
from pathlib import Path

# Resolve paths independently of the shell working directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent

def run_command(command):
    """Run a command and stop if it fails."""
    print(f"Running: {' '.join(map(str, command))}", flush=True)
    subprocess.run(command, cwd=PROJECT_DIR, check=True)

def main():
    # 1. Fetch emails.
    run_command([sys.executable, "-m", "ingestion.read_email"])

    # 2. Parse emails and regenerate meetings.json.
    run_command([sys.executable, "-m", "ingestion.parse_emails"])

    meetings_file = PROJECT_DIR / "data" / "meetings.json"
    if not meetings_file.is_file():
        raise FileNotFoundError(f"Expected file was not created: {meetings_file}")
    '''
    # 3. Stage only meetings.json.
    run_command(["git", "add", "--", "data/meetings.json"])

    # Check whether the staged meetings.json differs from HEAD.
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", "data/meetings.json"],
        cwd=PROJECT_DIR,
        check=False,
    )

    if result.returncode == 0:
        print("meetings.json has not changed; nothing to push.", flush=True)
        return
    if result.returncode != 1:
        raise RuntimeError("Could not determine whether meetings.json changed.")

    # 4. Commit and push the update.
    run_command([
        "git",
        "-c", f"user.name=ptown1",
        "-c", f"user.email=347249116+ptown1@users.noreply.github.com",
        "commit",
        "-m", "Update meeting schedule"
    ])
    run_command(["git", "push"])

    print("Meeting schedule successfully pushed to GitHub.", flush=True)
    '''

if __name__ == "__main__":
    main()
