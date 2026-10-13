# Final reading UX implementation plan

**Goal:** Keep the existing three public destinations and make one representative case readable in the order problem → original answer → professional feedback → complete evidence.

**Architecture:** Reuse formal-history selection, URL identity, per-page navigation state, native expanders and the shared evidence renderer. Change presentation only; retain management operations, data filtering, scoring, provider and recovery code.

**Tech Stack:** Streamlit 1.51, Python, existing native controls and shared CSS.

- [x] Verify local and remote HEAD are107ded8; inspect existing pages and preserve completed navigation/evidence behavior.
- [x] Add failing isolated regressions for reading order, collapsed selectors, demo-only operation, public library form removal and preserved historical evidence.
- [x] Adjust portfolio presentation; prefer saved runtime task when available and clearly mark current design otherwise.
- [x] Rename config stage to configuration example, retain old-session migration, remove disabled real-call action; keep only the existing history navigation as primary.
- [x] Limit public library to browse mode, keep controlled management form code and all reference content behind primary/secondary reading sections.
- [x] Run full regression, lint, raw-file and read-only runtime-table fingerprint checks: 985 passed, 7 skipped; Ruff and dataset validation passed; original fingerprints unchanged.
- [x] Inspect actual browser at1440/768/390/320, exercise switch/model/evidence/return/refresh; disclose unsupported true200% zoom and iPhone testing in the delivery report.
- [ ] Record accurate delivery report; commit/push code using existing authorization and verify actual deployed build. Never publish private data exports/screenshots or modify deployment credentials.
