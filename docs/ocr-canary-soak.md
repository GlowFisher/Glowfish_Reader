# OCR component canary and rollback

The public resident OCR runtime remains disabled by default during the observation
period. Start a canary with:

```powershell
$env:GLOWFISH_OCR_COMPONENT_RUNTIME = "component"
```

Use `0` or `legacy` as the immediate rollback:

```powershell
$env:GLOWFISH_OCR_COMPONENT_RUNTIME = "legacy"
```

## Observability

`GET /api/runtime/status` reports the selected policy, effective runtime, current
worker state, and session counters for:

- component attempts, successes, failures, and total duration;
- prewarm attempts, successes, and failures;
- legacy fallback attempts, successes, and failures;
- the most recent event and error type.

The same events are written as structured key-value records to the existing rotating
desktop runtime log. Image paths and recognized text are not logged.

## Default-enable gate

Do not change the default from legacy to component until a representative observation
period shows:

- no output-equivalence regression;
- a component failure rate below the agreed release threshold;
- successful legacy fallback for every injected or naturally occurring component
  failure;
- no sustained latency or memory regression;
- clean shutdown and idle worker release.

Changing the default is a separate release decision. The explicit `legacy` value must
remain supported for emergency rollback after default enablement.
