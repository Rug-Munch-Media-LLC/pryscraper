# PR Checklist

## Scope

- [x] Public legal imports remain unchanged.
- [x] New modules stay at or below 200 lines.
- [x] No dependency or lockfile changes.
- [x] No secrets, auth, or payment-verification behavior changed.

## Verification

- [x] `tests/test_legal_docs.py` passes.
- [x] `tests/test_x402_middleware.py` passes.
- [x] `scripts/check-structure.py` passes.
- [x] `scripts/check-antipatterns.py` passes without raising baselines.
- [x] Ruff check and format checks pass.
- [x] Full suite has no change-related failures; host-credential-sensitive
      tests pass when provider keys are unset.

## Delivery

- [x] `STATUS.md` and `MODULARITY.md` reflect the new queue state.
- [x] Commit uses a conventional message.
- [ ] Push the feature branch to Forgejo without force.
