# Security policy

## Supported versions
Only the latest release of Rubricon receives fixes.

## Reporting a vulnerability
Please do **not** open a public issue. Use GitHub's private vulnerability reporting (https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Security" tab -> "Report a vulnerability") on this repository. You should get an
acknowledgement within 7 days. Once a fix is released, the report is credited unless you ask otherwise.

Rubricon is research software that runs locally on files you provide. It makes no network calls
except where you explicitly configure an LLM provider. API keys are read from environment
variables and are never written to results.
