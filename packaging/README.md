# Release assembly

Only this repository may produce the signed Windows installer. The build must:

1. validate `component-manifest.json` against all four gitlinks;
2. build UI `dist/` and verify every file in its manifest;
3. verify every local model against OCR `models.lock.json`;
4. install the pinned OCR and Account packages, then run PyInstaller;
5. run capability and offline OCR selftests before signing;
6. emit installer SHA-256, SBOM, and the component manifest.

No build step may follow a component branch or read assets from an unrecorded path.
