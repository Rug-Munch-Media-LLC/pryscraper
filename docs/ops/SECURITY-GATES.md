# Security gates — container & supply chain

Status: 2026-10-18. Owner: ops. Companion to `docs/ops/COMPOSE-SERVICE-HYGIENE.md`
and the CI definition in `.forgejo/workflows/ci.yml`.

This file records **decisions**, not aspirations. A gate is either blocking or
it does not exist; an advisory gate that reports success is decoration.

## 1. Trivy — CRITICAL is blocking

| Scan | Scope | Severity | Behaviour |
|---|---|---|---|
| `trivy fs --scanners vuln` | dependency manifests + lockfiles (`requirements*.txt`, `requirements.docker.lock`) | CRITICAL | **blocking** (`--exit-code 1`) |
| `trivy fs --scanners secret` | repo tree (tests skipped — gitleaks owns those) | CRITICAL | **blocking** |
| `trivy config` | Dockerfile, compose files | CRITICAL | **blocking** |

HIGH findings are **not** in the scan invocation at all. That is deliberate: an
advisory HIGH step alongside a blocking CRITICAL step trains reviewers to
ignore the job. HIGH/MEDIUM are covered by the other blocking gates —
`pip-audit` (any advisory), OSV, SBOM verification and the dependency-freshness
report — so nothing is silently dropped, it is just owned by one gate.

**Exceptions** go in `docs/ops/trivy-ignore.yaml`. Each entry requires a
`statement` and an `expired_at` (≤90 days). When it expires Trivy stops
honouring it and the gate blocks again. There is no other suppression path:
`continue-on-error` on the scan steps is forbidden and is asserted by
`tests/test_production_readiness.py::test_no_security_gate_is_neutralised`
(the `ci.yml:trivy-scan:continue-on-error` carve-out was removed on
2026-10-18).

Residual risk: the Forgejo job container has no docker CLI, so `trivy fs`
scans **lockfiles**, not image layers. Base-image CVEs are therefore not caught
by this job. Closing that requires a docker-capable runner; until then the base
image stays digest-pinned (`python:3.12-slim@sha256:57cd7c3a…`) so the layer
content cannot change silently.

## 2. Image signing — removed, not faked

The `sign-image` job was `if: false` since 2026-09-12. It was a template
pointing at `registry.example.com` with `git.example.com` as the OIDC issuer,
and it could never have run:

- no container registry is published for this repo,
- the runner's job container has no docker CLI (`docker: command not found`),
- Forgejo does not expose the OIDC issuer that cosign keyless requires.

A permanently disabled job is worse than no job: it advertises a control that
does not exist. **The job was deleted on 2026-10-18.** Pry's supply-chain
guarantees are therefore: digest-pinned base image, lockfile-pinned deps,
blocking Trivy/pip-audit/OSV, SBOM generation + verification, and the
SLSA/scorecard workflows.

**Re-enable when all three are true:** a real `REGISTRY` with credentials, a
docker-capable runner, and an OIDC issuer trusted by cosign (or a
long-lived key pair stored as a CI secret). The ad-hoc path for operators who
build locally:

```bash
# Keyless (needs an OIDC token from a supported issuer)
COSIGN_EXPERIMENTAL=1 cosign sign --yes "$REGISTRY/pryscraper:$TAG"
# Key-based fallback (no OIDC)
cosign sign --key cosign.key "$REGISTRY/pryscraper:$TAG"
cosign verify --key cosign.pub "$REGISTRY/pryscraper:$TAG"
```

Verification is only meaningful if deployment enforces it — an unverified
signature is a log line, not a gate.

## 3. Build context — `.dockerignore`

`.dockerignore` is a security control, not just a build-speed knob:
`COPY . ./` bakes whatever it lets through into the runtime image.

Excluded and why: `data/`, `datasets/`, `sessions/`, `pry-data/` (scraped
data must never ship in a public image), `.cache/`, `.coverage*`, `dist/`,
`build/`, `node_modules`, `website/` (docs site; `website/node_modules` alone
was 310 MB), tests, `.env*`, VCS metadata.

Measured before the change: `COPY . ./` was **281 MB**. After: see the build
report in the commit message / `docker history`.

## 4. Image size

The 2026-10-18 changes remove two structural sources of bloat:

1. `COPY . ./` then `chown -R pry:pry /app` duplicated the whole app tree into
   a second layer (**284 MB** measured). The user is now created before the
   copy and `COPY --chown=pry:pry` applies ownership in the copy layer.
2. The docs site and its `node_modules` were inside the build context
   (~280 MB of the copy layer).

The runtime apt install was also collapsed into a single transaction
(chromium + tesseract + postgresql-client + deps). Chromium and the Playwright
browser bundle are both kept: `src/pry/engine/browser_pool.py` deliberately
cross-checks the system `/usr/bin/chromium` major version against the
Playwright driver, so removing either one would break browser launches at
runtime for a modest size win.
