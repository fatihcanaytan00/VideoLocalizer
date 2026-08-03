# YouTubeLocalizer v0.1.0

Automatically translates a YouTube video's title and description into multiple
languages and writes them back to YouTube as
[localizations](https://developers.google.com/youtube/v3/docs/videos) — the
original title/description stay exactly as uploaded; translated versions are
added alongside them, and YouTube shows the right one to each viewer based on
their locale.

This is an MVP backend tool: no GUI, no packaged executable, config-file
driven, run from the command line.

## What it does

1. Picks a video (latest upload, or a specific video ID you give it)
2. Reads its title and description
3. Translates both into every language configured in `config/config.yaml`
4. Writes the translations back to YouTube, merging with (not overwriting)
   any localizations that already exist for languages you didn't just
   generate

Supports multiple YouTube accounts — each with its own OAuth credentials and
cached login — selected per run with `--account`.

## Requirements

- Python 3.10+
- A Google Cloud project with the **YouTube Data API v3** enabled
- One OAuth client (type: **Desktop app**) per YouTube account you want to
  localize videos on

## Installation

```bash
pip install -r requirements.txt
pip install -e .
```

The second command does an editable install so the tool can be run as a
module (`python -m youtubelocalizer.main`) from any working directory,
without manually setting `PYTHONPATH`. You only need to run it once, unless
`pyproject.toml` changes.

Verify the install:

```bash
python -m youtubelocalizer.main --version
```

## Google Cloud OAuth setup

Do this once per YouTube account you plan to run the tool against.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and
   select or create a project.
2. **APIs & Services → Library** → search for **YouTube Data API v3** →
   Enable.
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
   - If prompted, configure the OAuth consent screen first (External is
     fine for personal use; add your own Google account as a test user if
     the app stays in "Testing" status).
   - Application type: **Desktop app**.
4. Download the resulting JSON credentials file.

Repeat for each additional YouTube account (a separate Cloud project isn't
required — you can create multiple OAuth clients in one project, one per
account you'll authenticate).

## Account configuration

Each YouTube account the tool can run against is an **account profile** in
[`config/accounts.yaml`](config/accounts.yaml):

```yaml
accounts:
  - name: main_channel
    client_secret_file: config/accounts/main_channel/client_secret.json
    token_file: config/accounts/main_channel/token.json
```

Setup steps:

1. Rename the placeholder entries (`account_1`, `account_2`, ...) to
   something recognizable, e.g. `main_channel`.
2. Create the matching folder under `config/accounts/<name>/` if it doesn't
   already exist.
3. Save the OAuth JSON you downloaded from Google Cloud Console as
   `config/accounts/<name>/client_secret.json`.
4. Leave `token_file` alone — it's created automatically the first time you
   authenticate that account (see below).

`client_secret.json` and `token.json` are gitignored — never commit them.

## config.yaml settings

[`config/config.yaml`](config/config.yaml) holds settings shared across every
account:

| Key | Meaning |
|---|---|
| `source_language` | Language your original titles/descriptions are written in (e.g. `tr`) |
| `target_languages` | List of language codes to generate localizations for |
| `translation.provider` | Translation backend — only `deep_translator_google` exists in v0.1.0 |
| `logging.directory` / `logging.level` | Where per-run log files go, and at what verbosity |
| `protected_terms` | Optional list of names/titles (channel name, game titles, etc.) that must survive translation unchanged — matched case-insensitively |

## Running

First run for a given account triggers an interactive OAuth consent flow —
your browser opens, you sign in and approve, and a token is cached so
subsequent runs don't prompt again (it refreshes silently until you revoke
access).

```bash
# Localize the latest upload on an account
python -m youtubelocalizer.main --account main_channel

# Localize a specific video instead of the latest upload
python -m youtubelocalizer.main --account main_channel --video-id VIDEO_ID

# Show help / all options
python -m youtubelocalizer.main --help

# Show version
python -m youtubelocalizer.main --version
```

Each run prints a summary:

```
=== Localization Summary ===
Video: <title> (<video_id>)
Languages updated (N): German, French, ...
Languages failed (0): -
Quality warnings (0): -
```

A non-zero exit code means at least one language failed — check the summary
and the log file for details. A full per-run log (console output plus
`DEBUG`-level detail if configured) is written to
`logs/run_<timestamp>_<account>.log`.

## Troubleshooting

**`Config file not found: config/config.yaml` / `config/accounts.yaml`**
Run the command from the project root (the directory containing `config/`),
not from inside `src/` or `scripts/`.

**`Unknown account 'X'. Available accounts: ...`**
The `--account` value must match a `name:` entry in `config/accounts.yaml`
exactly (case-sensitive).

**`OAuth client secret file not found: ...`**
You haven't placed `client_secret.json` at the path configured for that
account yet — see [Account configuration](#account-configuration) above.

**Browser doesn't open / consent flow hangs**
`InstalledAppFlow.run_local_server()` needs a free local port and a default
browser it can launch. If you're on a headless machine, this flow won't
work as-is — v0.1.0 doesn't support the alternate copy-paste console flow.

**A language fails with "No translation was found using the current
translator"**
The free `deep-translator`/Google Translate backend occasionally can't
translate very short or unusual text (e.g. a title that's just a camera
filename like `IMG_1234`). This is a per-language failure — every other
language in the run still succeeds and gets written; check the summary's
"Languages failed" section for the exact error.

**A language succeeds but shows a "Quality warning"**
Lightweight heuristics (empty output, output identical to source, output
suspiciously similar to source) flag likely-bad translations without
blocking the write. Worth a manual look, especially for short titles — some
false positives are expected (e.g. a URL or product name that's correctly
identical in both languages).

**Titles/descriptions look garbled in the terminal**
This is almost always a console codepage limitation (e.g. Windows
`cp1254`), not corrupted data — the data written to YouTube is correct
UTF-8 regardless of how it renders in your terminal. If in doubt, check the
video directly on YouTube or in the log file.

**Reading back localizations right after a run shows them missing**
YouTube's API has a brief read-after-write propagation delay — a video you
just updated may not reflect the change in a read a second later. Wait a
few seconds and re-check; this doesn't indicate the write failed.

**Quota errors**
The YouTube Data API has a default daily quota of 10,000 units. A full run
across `N` target languages costs roughly `3 + 50 = 53` units total (one
batched write, not one per language), so this should only come up from
running very frequently or against many accounts in a single day.
