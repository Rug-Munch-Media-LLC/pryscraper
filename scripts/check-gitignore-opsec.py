#!/usr/bin/env python3
"""Assert the global opsEC gitignore blocks credential MATERIAL and allows SOURCE.

Bug (2026-09-30): /root/.gitignore_global used the bare substrings `*credentials*`
and `*credential*`. Unanchored, git matched them at ANY depth, so every path
containing "credential" was silently hidden from `git add` — a commit shipped that
imported a module (src/pry/api/credential_vault.py) which was never in the tree.

This script tests REAL git behaviour with `git check-ignore --no-index`, not a
regex reimplementation. It creates NO files and reads NO credential content; it
only asks git which rules match a hypothetical path.

Exit 0 = every expectation held. Exit 1 = at least one violated (CI gate).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Resolved once to an absolute path: a partial executable path is a PATH-hijack
# vector in a CI gate (ruff S607). Matches scripts/apify-push-all.py convention.
GIT = shutil.which("git") or "/usr/bin/git"

# (path, should_be_ignored, why)
BLOCKED: tuple[tuple[str, str], ...] = (
    ("credentials.json", "root credential dump"),
    ("config/credentials.yaml", "credential material in config/"),
    ("deep/nested/credentials.json", "credential material at depth"),
    ("deep/nested/deeper/credentials.yml", "credential material, deeper still"),
    ("secrets/credentials.json", "inside a secrets dir"),
    (".credentials", "dotfile credential store"),
    (".credentials.json", "dotfile credential dump"),
    ("deploy.credentials", "dot-suffixed credential file"),
    ("app.credentials", "dot-suffixed credential file"),
    ("credentials.json.bak", "credential dump backup copy"),
    ("deep/nested/credential.toml", "singular basename, toml"),
    ("deep/nested/credential.ini", "singular basename, ini"),
    ("deep/nested/credential.xml", "singular basename, xml"),
    ("deep/nested/credential.env", "singular basename, env"),
    ("deep/nested/credential.txt", "secrets pasted to txt"),
    ("mycredentials.json", "embedded-suffix dump — BLOCKED, see note"),
    ("id_rsa", "ssh private key"),
    ("config/id_rsa.pem", "ssh key in subdir"),
    ("deep/id_ed25519", "ed25519 private key"),
    ("data/vault.json", "wallet/vault dump"),
    ("server.pem", "tls key material"),
    ("server.key", "private key material"),
    ("api.p12", "pkcs12 bundle"),
    ("app.jks", "java keystore"),
    ("thing.secret", "secret file"),
    (".env", "env file with values"),
    (".env.production", "env file with values"),
)

ALLOWED: tuple[tuple[str, str], ...] = (
    ("src/pry/api/credential_vault.py", "the module that was dropped from a commit"),
    ("src/pry/api/credential_vault_reads.py", "same"),
    ("src/pry/compliance/credential_scope.py", "real source module"),
    ("src/pry/payments/x402_middleware/credential.py", "real source module"),
    ("tests/x402/test_gate_credential_lifecycle.py", "needed `git add -f` before"),
    ("tests/test_authz_credential_scope.py", "real test module"),
    ("src/pry/api/auth_connector.py", "auth source, no false positive"),
    ("src/pry/keys.py", "key-ish source is not key material"),
    ("src/pry/keystore.py", "keystore source is not a keystore"),
    ("src/pry/secretly.py", "'secret' in a source name is fine"),
    ("README.md", "ordinary file"),
    ("src/pry/main.py", "ordinary source"),
    ("docs/credentials.md", "documentation about credentials"),
    ("apps/web/src/app/api/user/export/credentials/route.ts", "REAL tracked file in degenfeed-web"),
    ("credentials_test_helper.py", "test helper mentioning credentials"),
    ("src/pry/compliance/credentials_rotation.md", "docs about rotation"),
)


def ignored(repo: Path, rel: str) -> bool:
    """True when git's rules ignore `rel`, ignoring whether it is already tracked.

    --no-index is REQUIRED: a tracked file always reports 'not ignored' otherwise,
    which would make this whole check silently vacuous.
    """
    return (
        subprocess.run(  # noqa: S603 - absolute GIT path, fixed argv, '--' guards the path
            [GIT, "check-ignore", "-q", "--no-index", "--", rel],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def source_rule(repo: Path, rel: str) -> str:
    out = subprocess.run(  # noqa: S603 - absolute GIT path, fixed argv, '--' guards the path
        [GIT, "check-ignore", "-v", "--no-index", "--", rel],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    parts = out.stdout.strip().split("\t")
    return f"{parts[0].split('/')[-1]}:{parts[1]}" if len(parts) >= 2 else "?"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="opsec-check-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run([GIT, "init", "-q"], cwd=repo, check=True)  # noqa: S603 - fixed argv
        failures: list[str] = []

        print(f"repo: {repo}\n")
        print("=== MUST BE BLOCKED (credential material / secrets) ===")
        for rel, why in BLOCKED:
            hit = ignored(repo, rel)
            mark = "ok  BLOCKED" if hit else "!!  LEAKED"
            if not hit:
                failures.append(f"LEAK: {rel} is NOT ignored (expected blocked)")
            rule = source_rule(repo, rel) if hit else "-"
            print(f"  {mark}  {rel:<44} [{why}] <- {rule}")

        print("\n=== MUST BE ALLOWED (legitimate source / docs) ===")
        for rel, why in ALLOWED:
            hit = ignored(repo, rel)
            mark = "ok  ALLOWED" if not hit else "!!  WRONGLY BLOCKED"
            if hit:
                failures.append(
                    f"FALSE POSITIVE: {rel} is ignored by "
                    f"{source_rule(repo, rel)} (expected allowed)"
                )
            rule = source_rule(repo, rel) if hit else "-"
            print(f"  {mark}  {rel:<44} [{why}] <- {rule}")

    print()
    if failures:
        print(f"FAIL — {len(failures)} expectation(s) violated:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASS — {len(BLOCKED)} blocked, {len(ALLOWED)} allowed, all expectations held.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
