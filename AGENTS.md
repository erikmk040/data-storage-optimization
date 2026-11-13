# Project instructions

## My role: C (Search, API & UI)

Files I own: `src/search/*`, `app/*`

Run the app:

```bash
streamlit run app/streamlit_app.py
```

Rebuild mock data:

```bash
python3 -m src.search.make_mock
```

Build a video package (Roll A):

```bash
python3 -m src.video.package path/to/recording.mp4 --output data/sample/recording
```

For a frame-only smoke test without downloading a Whisper model:

```bash
python3 -m src.video.package path/to/recording.mp4 --output data/sample/recording --skip-transcription
```

Rules:

- Never edit `docs/schema.md` or other roles' folders; propose changes instead.
- Always work on a feature branch, never on `main`.
- Keep generated files under `data/` out of commits unless the team explicitly asks for them.
- Before committing, run the mock-data/index/search smoke test and inspect the diff.
