# Security

Minuta is a private-library server. Take the credential model seriously.

## Reporting

Do not open public issues for vulnerabilities (auth bypass, secret leakage,
 SSRF via URL inputs, prompt injection through transcript content).
Contact the maintainer privately; include reproduction steps and impact.
We aim to acknowledge within 72 hours.

## Rules the codebase follows

- Bearer tokens required on all `/v1`, `/admin`, and `/mcp` routes.
- Transcript text is untrusted data: quoted and cited, never executed.
- Logs redact secrets (`settings.redaction_values`); API keys are stored
  as hashes, shown once at creation.
- `.env` is gitignored. If you ever commit a secret: revoke it first,
  then purge it from history — revocation before cleanup, always.
