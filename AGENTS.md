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

Rules:

- Never edit `docs/schema.md` or other roles' folders; propose changes instead.
- Always work on a feature branch, never on `main`.
- Keep generated files under `data/` out of commits unless the team explicitly asks for them.
- Before committing, run the mock-data/index/search smoke test and inspect the diff.
