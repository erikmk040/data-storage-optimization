# Ericsson Knowledge Compression — three-minute jury script

The same script is embedded as speaker notes in the presentation.

## Slide 1 — 0:00–0:30

The brief creates a real tension for three users. Storage owners see large files and copies grow. Knowledge workers cannot find one answer without replaying content. Offboarding teams cannot safely delete a file unless another accessible copy is proven. The causes are full-fidelity media, duplication and information that is not indexed. The symptom is expensive retention or lost knowledge. Can we keep what matters without keeping every byte?

## Slide 2 — 0:30–1:00

We tested the idea on a real six-minute video. The 88,654,139-byte source became a 1,202,334-byte knowledge package: 98.64 percent less storage. It still contains 33 searchable transcript segments and 16 representative frames. This is measured, not projected. Semantic mode does not preserve original audio or every motion frame. Exact mode is available when byte-for-byte recovery matters, but cannot give this reduction.

## Slide 3 — 1:00–1:30

Not every byte has the same value. We preserve words, timing and useful visuals, avoid duplicate information and create one package for search and AI. Our innovation is not an exotic codec. It is the combination of semantic reduction, content identity, activation and deletion evidence. We built the package pipeline, policies, search, API and demo; we reused established codecs and extraction tools.

## Slide 4 — 1:30–1:55

The website is only the demo client. The product is the Python core and versioned REST API behind it. It can sit between Ericsson Play, SharePoint, OneDrive or offboarding and existing storage, search and AI systems. The API and streamed video path work today. Ericsson authentication, product connectors and governed deletion approval come next; the prototype never deletes automatically.

## Slide 5 — 1:55–2:30 — live demo

Open the demo and show the prepared real-video result: **88.7 MB → 1.20 MB → 98.64% reduction**. Search for `winner` and show transcript plus actual frames. Say that **44 tests pass** and the full upload was verified. Do not transcribe on stage. If the live demo fails, use the measured backup on the slide.

If the live demo fails, use the verified result printed on the slide.

## Slide 6 — 2:30–3:00

We know the measured reduction, search path and deployable API work. The biggest risk is choosing a fidelity policy users trust on representative Ericsson data. Our next step is a four-week, read-only pilot on 100 files with a data owner, integration engineer and security or records reviewer. We measure savings, search relevance, fidelity acceptance and processing cost. No automated deletion during the pilot. Thank you.
