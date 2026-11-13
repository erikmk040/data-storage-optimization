# Local test inputs

Put local videos and documents here when testing the pipeline. The media files
are ignored by Git, so they will stay on your machine and will not be pushed.

Suggested files:

- `C2L_Presentation_Hackathon_RevB.pdf`
- `Jury and prizes.mp4`
- `GraalVMs_Ahead-of-Time_Compilation_(Source).mp4`

Example:

```bash
python -m src.video.package \
  "data/test_inputs/Jury and prizes.mp4" \
  --output data/sample/jury_prizes
```
