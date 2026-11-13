# Data and privacy

The web service binds to `127.0.0.1` by default. Keep it on loopback: it does
not provide authentication or a secure remote-access gateway.

Audio is captured on the Mac. ScreenCaptureKit is configured with an audio
output only; the application does not receive or save screen frames. macOS
may still display its screen/audio-capture indicator. Capture requires the
permissions requested by macOS and starts only after the user starts it.

Captured audio is sent to the configured Doubao ASR service. Query text,
conversation history and selected reference material are sent to the
configured LLM endpoint. Both answer routes use that endpoint. This is not
an offline application. Only send material you are authorized to process.

Recordings, transcripts, answers and diagnostics are stored under `var/`.
Exported experiments and screenshots belong under `output/`. Audio retention
is enabled by default for playback and diagnostics; set
`RETAIN_UTTERANCE_AUDIO` to `"0"` to remove completed per-utterance files.
The original session recording is retained separately. The clear-history
button resets LLM history; it is not a delete-all-recordings command.

Agent tools are read-only and restricted to the configured material root,
allowlisted subdirectories and extra files. They exclude symlinks, common
credential/dependency directories and oversized files. Common credentials,
phone numbers and email addresses are redacted, but redaction cannot detect
all confidential content. Review the files you allow before using the agent.

The following are ignored by Git: `config.local.json`, `.env*` (except the
example), `secrets/`, `materials/`, `private/`, `var/`, `output/`, recordings,
documents, local service plists, dependencies and native build products.
Do not force-add private files or place private material in public examples.

Before committing, stage the intended public files and run:

```sh
python3 scripts/check_public.py
git diff --cached --stat
git diff --cached
```

The checker scans staged blobs and file names, not just working-tree files.
It detects common mistakes; manual review is still needed. If a credential
has already been pushed, revoke it and remove it from Git history. Adding an
ignore rule does not remove an existing commit.
