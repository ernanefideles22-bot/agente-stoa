# STOA v1 Closeout

## Status

STOA v1 is closed for the audited scope of the main backend and the main interface served by `GET /`.

## Closed Scope

- Main command flow through `POST /api/command`.
- Two-step execution contract with `preview -> apply/cancel` per session.
- Pending preview persistence and inspection through `GET /api/pending-preview/{session_id}`.
- Pending preview cleanup after `apply`, `cancel`, and failed `apply`.
- Main interface integration with explicit preview display, `apply`, `cancel`, ambiguity blocking, and preview restoration after reload.
- Automated regression coverage for backend critical flow and main shell contract.
- Real-browser validation of the main interface flow in local Microsoft Edge.

## Closing Evidence

### Backend

- Pending preview model and storage in `app/main.py`.
- `POST /api/command` handles:
  - preview creation
  - preview reuse protection
  - `apply`
  - `cancel`
  - cleanup on failure
- `GET /api/pending-preview/{session_id}` exposes current pending state.
- Session history and audit log record the command cycle.

### Main Interface

- Main shell exposes `#previewPanel`, `#previewApplyBtn`, and `#previewCancelBtn`.
- UI blocks ambiguous new commands while preview is pending.
- UI restores pending preview by session after reload.
- UI clears state after `apply`, `cancel`, and `409` preview-missing errors.
- Command routing mode toggles persist across reload so the same session stays on the same command path.

### Automated Validation

- `python -m py_compile app\main.py tests\test_app.py`
- `python -m unittest tests.test_app -v`

Current result at closeout:

- 19 tests passing

### Real Browser Validation

Validated in local Microsoft Edge against `http://127.0.0.1:18000`:

- normal command submission
- preview visible in UI
- ambiguity blocked while preview pending
- preview restored after reload
- `cancel` via UI
- `apply` via UI
- backend error reflected after `apply` without pending preview

Observed session used during final browser validation:

- `ui-trace-c21ef895`

Observed UI outputs included:

- `Preview pronto.`
- `Preview cancelado. Nenhuma ação foi aplicada.`
- `Hora: 16:16:00`
- `Data: 2026-04-14`
- `Nenhum preview pendente para aplicar.`

## Explicitly Out of Scope

- `stoa_mobile.html` alignment with the v1 main-shell flow.
- Human manual validation on a real mobile device.
- Cleanup of legacy warnings such as `@app.on_event("startup")` and `datetime.utcnow()`.
- Non-critical visual polish and secondary-channel hardening.

## Residual Risks

- Main shell is closed, but secondary interfaces are not part of this release boundary.
- Browser validation was real but headless; no visible-window manual pass was executed.
- Avatar WebSocket disconnect noise appears during browser teardown and was not treated as a v1 blocker because it did not break the validated critical flow.

## Release Boundary

No architecture reopening, contract changes, or redesign work are part of this closeout.
