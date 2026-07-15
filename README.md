# Glowfish OCR

Independent local OCR component for Glowfish Reader.

- Public package: `glowfish_ocr`
- Current worker implementation: `legacy/`
- Regression corpus and reports: `bench/`
- Model integrity contract: `models.lock.json`

The public package does not import Host, UI, or Account code. Source images are processed locally only.
