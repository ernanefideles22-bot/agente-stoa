# STOA v1.1 Hardening Backlog

This backlog is intentionally separated from the closed v1 scope. Items below do not reopen the v1 architecture or contracts unless a production defect proves that necessary.

## Priority 1

- Align `stoa_mobile.html` with the main-shell preview contract already closed in v1.
- Run a human validation pass on a real mobile device for the main interface served by `GET /`.
- Reduce teardown noise from avatar WebSocket disconnects during browser close/shutdown.
- Add an end-to-end visible-browser acceptance script that can be reused without reworking the app.

## Priority 2

- Replace deprecated `@app.on_event("startup")` usage with lifespan handlers.
- Replace deprecated `datetime.utcnow()` usage with timezone-aware UTC timestamps.
- Review cleanup of temporary runtime artifacts used during local validation.
- Expand automated coverage for UI state restoration and mode persistence with a browser-level runner.

## Priority 3

- Review secondary-interface parity for `stoa_mobile.html` and any future Android/web shell integrations.
- Add explicit operational documentation for browser shutdown noise vs. real runtime failures.
- Audit non-critical UX polish in the main shell without redesigning the closed v1 interaction model.

## Not Included Here

- No redesign.
- No new command architecture.
- No contract rewrite for `POST /api/command`.
- No broad backend refactor.
