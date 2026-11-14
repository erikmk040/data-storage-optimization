# Ericsson Knowledge Compression — three-minute jury script

The same script is embedded as speaker notes in the presentation.

## Slide 1 — 0:00–0:30

The brief creates a real tension for four users. Storage owners see large files and copies grow. Knowledge workers cannot find one answer without replaying content. Offboarding teams cannot safely delete a file unless another accessible copy is proven. AI and data teams cannot activate information trapped in media. The causes are full-fidelity media, duplication and information that is not indexed. Can we keep what matters without keeping every byte?

## Slide 2 — 0:30–1:00

We tested the idea on a real six-minute video. The 88,654,139-byte source became a 1,202,334-byte knowledge package: 98.64 percent less storage. It still contains 33 searchable transcript segments and 16 representative frames. This is verified local benchmark evidence; the source is not distributed in the repository. For a clean-clone control, exact mode reduces the tracked challenge document from 285,883 to 275,774 bytes, or 3.54 percent, and restores it byte-for-byte. Semantic mode does not preserve original audio or every motion frame.

## Slide 3 — 1:00–1:30

Not every byte has the same value. We preserve words, timing and useful visuals, avoid duplicate information and create one package for search and AI. Our innovation is not an exotic codec. It is the combination of semantic reduction, content identity, activation and deletion evidence. We built the package pipeline, policies, search, API and demo; we reused established codecs and extraction tools.

## Slide 4 — 1:30–1:55

The website is only the demo client. The product is the Python core and versioned REST API behind it. It can sit between Ericsson Play, SharePoint, OneDrive or offboarding and existing storage, search and AI systems. The API and streamed video path work today. Ericsson authentication, product connectors and governed deletion approval come next; the prototype never deletes automatically.

## Slide 5 — 1:55–2:30 — live demo

If the prepared local artifact is available, show **88.7 MB → 1.20 MB → 98.64% reduction**. Otherwise say that the clean demo uses deterministic mock search and use the benchmark-evidence slide. Search for `winner` and show transcript plus visual context. Say that the automated release suite covers exact restoration, semantic search and the API contract. Do not transcribe on stage.

If the live demo fails, use the clearly labelled local benchmark evidence printed on the slide.

## Slide 6 — 2:30–3:00

We know the measured reduction, search path and deployable API work. The biggest risk is choosing a fidelity policy users trust on representative Ericsson data. Our next step is a four-week, read-only pilot on 100 files with a data owner, integration engineer and security or records reviewer. We measure savings, search relevance, fidelity acceptance and processing cost. No automated deletion during the pilot. Thank you.
