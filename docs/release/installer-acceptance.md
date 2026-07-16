# Windows Installer Acceptance

Use this checklist on a disposable Windows user account or clean virtual-machine
snapshot. Do not run upgrade or uninstall acceptance against a developer's normal
profile.

## Inputs

- The versioned `Glowfish Reader V<version> Setup.exe`.
- The matching `update.json`.
- The expected SHA-256 from the release job.
- A representative document and one OCR fixture that contain no sensitive data.

Verify the installer hash before execution:

```powershell
Get-FileHash ".\Glowfish Reader V2.0.0 Setup.exe" -Algorithm SHA256
Get-AuthenticodeSignature ".\Glowfish Reader V2.0.0 Setup.exe"
```

Public release requires a valid organization code-signing signature. An unsigned
installer is suitable only for internal acceptance.

## Clean Install

1. Start from a clean snapshot or disposable local Windows account.
2. Run the installer interactively.
3. Confirm no administrator prompt is required.
4. Confirm the application installs under
   `%LOCALAPPDATA%\Programs\Glowfish Reader V<version>`.
5. Confirm Start Menu and selected desktop shortcuts open the installed executable.
6. Confirm the application starts, opens a representative document, performs
   offline OCR, exports an image, and writes its runtime log under the configured
   user-data root.
7. Confirm `/api/runtime/status` is reachable from the local application service
   and reports the expected OCR policy.

## In-place Upgrade

1. Install the previous accepted version first.
2. Create a small library entry, annotation, setting change, and login-state test
   record under the disposable profile.
3. Record the user-data directory contents and file hashes.
4. Run the new installer with `/SILENT /NORESTART`.
5. Confirm only one installed-product entry exists for the stable installer AppId.
6. Confirm the application restarts at the new version.
7. Confirm the library, annotation, settings, and disposable login-state records
   remain available.
8. Repeat the document, OCR, export, and runtime-status smoke checks.

## Uninstall

1. Close the application and run its uninstaller.
2. Confirm the installed program directory, Start Menu shortcut, desktop shortcut,
   and installed-product entry are removed.
3. Confirm the user-data directory still exists and retains the records created
   during upgrade acceptance.
4. Reinstall the same accepted version and confirm the retained data is readable.

## Release Evidence

Record:

- Windows version and architecture.
- Clean-install, upgrade, uninstall, and reinstall results.
- Installer file size, SHA-256, and signature status.
- Previous and new application versions.
- OCR policy used for the smoke run.
- Any Restart Manager prompt or process that prevented replacement.

Do not publish `update.json` until the signed installer is uploaded and its remote
SHA-256 has been verified. Publish the manifest last.
