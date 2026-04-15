# Release: STOA v1 Closeout

## Summary

This PR closes the audited v1 scope for STOA without reopening architecture or changing central contracts.

## Closed in This Release

- backend critical flow through `POST /api/command`
- preview pending state per session
- `apply` and `cancel`
- cleanup of pending state after `apply`, `cancel`, and failed `apply`
- main interface integration with visible preview and explicit controls
- preview restoration after reload by session
- ambiguity blocking while preview is pending
- automated regression coverage
- real-browser validation of the main interface flow

## Evidence

Automated:

- `python -m py_compile app\main.py tests\test_app.py`
- `python -m unittest tests.test_app -v`
- current result: 19 tests passing

Real browser:

- validated in Microsoft Edge against `http://127.0.0.1:18000`
- covered preview visible, apply, cancel, restore after reload, ambiguity blocking, and backend error with no pending preview

## Documentation Added

- `docs/release-v1-closeout.md`
- `docs/release-v1.1-hardening-backlog.md`
- README closeout and scope references

## Explicitly Out of Scope

- `stoa_mobile.html`
- human mobile-device validation
- legacy warning cleanup
- non-critical polish outside the validated v1 boundary

## Residual Risks

- secondary interfaces are not part of this release boundary
- browser validation was real but headless
- avatar WebSocket disconnect noise still appears on teardown
