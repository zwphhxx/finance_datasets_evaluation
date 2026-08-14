"""Editorial report presentation rules shared by review pages.

The rules deliberately use the existing warm-paper tokens and report-like
separators.  They contain no page data or Streamlit control flow.
"""

REPORT_STYLE_CSS = r"""
.report-masthead {
    border-bottom: 1px solid var(--fde-line-strong);
    border-top: 2px solid var(--fde-ink);
    color: var(--fde-ink);
    display: block !important;
    height: auto !important;
    margin: 0.75rem 0 1.5rem;
    padding: 1.25rem 0 1.35rem;
    visibility: visible !important;
}
.report-eyebrow {
    color: var(--fde-gold);
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    line-height: 1.4;
    margin: 0 0 0.48rem;
}
.report-masthead-title,
[data-testid="stMarkdownContainer"] .report-masthead-title {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: clamp(2rem, 4.5vw, 3.8rem) !important;
    font-weight: 650;
    letter-spacing: -0.025em;
    line-height: 1.13 !important;
    margin: 0;
    max-width: 52rem;
    padding: 0 !important;
}
.report-masthead-description {
    color: var(--fde-muted);
    font-size: 0.98rem;
    line-height: 1.65;
    margin: 0.72rem 0 0;
    max-width: 52rem;
}
.report-ledger {
    border-bottom: 1px solid var(--fde-line);
    border-top: 1px solid var(--fde-line);
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    margin: 0 0 1.75rem;
    padding: 0;
}
.report-ledger-item {
    border-right: 1px solid var(--fde-line);
    margin: 0;
    min-width: 0;
    padding: 0.78rem 0.85rem 0.82rem 0;
}
.report-ledger-item + .report-ledger-item {
    padding-left: 0.85rem;
}
.report-ledger-item:last-child {
    border-right: 0;
}
.report-ledger dt,
.report-ledger dd {
    margin: 0;
}
.report-ledger dt {
    color: var(--fde-muted);
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    line-height: 1.4;
}
.report-ledger dd {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1.12rem;
    line-height: 1.35;
    margin-top: 0.22rem;
    overflow-wrap: anywhere;
}
.report-section {
    border-top: 1px solid var(--fde-line-strong);
    margin: 2.3rem 0 0;
    padding: 1.25rem 0 0;
}
.report-section-heading {
    display: grid !important;
    gap: 1rem;
    grid-template-columns: 3.8rem minmax(0, 1fr);
    height: auto !important;
    margin-bottom: 1.05rem;
    min-width: 0;
    visibility: visible !important;
}
.report-section-index {
    color: var(--fde-gold);
    font-family: var(--fde-serif);
    font-size: 1.15rem;
    line-height: 1.2;
    padding-top: 0.08rem;
}
.report-section-label {
    color: var(--fde-muted);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    line-height: 1.4;
    margin: 0 0 0.22rem;
}
.report-section-title,
[data-testid="stMarkdownContainer"] .report-section-title {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1.55rem;
    font-weight: 650;
    line-height: 1.28;
    margin: 0;
    padding: 0 !important;
}
.report-section-body {
    color: var(--fde-text);
    margin-left: 4.8rem;
    min-width: 0;
    overflow-wrap: anywhere;
}
.report-index {
    border-top: 1px solid var(--fde-line-strong);
    margin: 0;
}
.report-index-row {
    border-bottom: 1px solid var(--fde-line);
    display: grid;
    grid-auto-columns: minmax(0, 1fr);
    grid-auto-flow: column;
    min-width: 0;
}
.report-index-row--header {
    color: var(--fde-muted);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
}
.report-index-row--active {
    border-left: 2px solid var(--fde-gold);
    color: var(--fde-ink);
}
.report-index-cell {
    min-width: 0;
    overflow-wrap: anywhere;
    padding: 0.72rem 0.8rem;
}
.report-index-cell:first-child {
    padding-left: 0;
}
.report-index-cell:last-child {
    padding-right: 0;
}
.report-index-cell::before {
    display: none;
}
.conclusion-model-index .report-index-row {
    grid-auto-flow: initial;
    grid-template-columns:
        minmax(0, 1.05fr)
        minmax(0, 0.82fr)
        minmax(0, 1.2fr)
        minmax(0, 2fr);
}
.st-key-conclusion_model_index [class*="st-key-conclusion_model_action_"] {
    border-bottom: 1px solid var(--fde-line);
    display: flex;
    justify-content: flex-end;
    padding: 0.25rem 0 0.6rem;
}
.st-key-conclusion_model_index [class*="st-key-conclusion_model_action_"] .stButton > button {
    max-width: 100%;
    min-height: 2.25rem;
    overflow-wrap: anywhere;
    white-space: normal;
    width: auto;
}
.evidence-index {
    border-top: 1px solid var(--fde-line-strong);
    margin: 0;
    min-width: 0;
}
.evidence-index-list {
    list-style: none;
    margin: 0;
    padding: 0;
}
.evidence-index-item {
    border-bottom: 1px solid var(--fde-line);
    display: grid;
    gap: 0.78rem;
    grid-template-columns: 0.7rem minmax(0, 1fr);
    min-width: 0;
    padding: 1rem 0;
}
.evidence-index-rail {
    background: var(--fde-gold);
    min-height: 100%;
    width: 1px;
}
.evidence-index-content {
    min-width: 0;
}
.evidence-index-head {
    align-items: baseline;
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.65rem;
}
.evidence-index-case,
.evidence-index-model,
.evidence-index-reason {
    font-size: 0.78rem;
    line-height: 1.45;
    overflow-wrap: anywhere;
}
.evidence-index-case {
    color: var(--fde-gold);
    font-family: var(--fde-serif);
    font-weight: 700;
}
.evidence-index-model {
    color: var(--fde-muted);
}
.evidence-index-reason {
    color: var(--fde-ink);
    font-weight: 650;
}
.evidence-index-title {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1.15rem;
    font-weight: 650;
    line-height: 1.4;
    margin: 0.38rem 0 0;
    overflow-wrap: anywhere;
}
.evidence-index-details {
    display: grid;
    gap: 0.7rem 1rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin: 0.72rem 0 0;
    min-width: 0;
}
.evidence-index-details > div {
    border-top: 1px solid var(--fde-line);
    min-width: 0;
    padding-top: 0.42rem;
}
.evidence-index-details dt,
.evidence-index-details dd {
    margin: 0;
}
.evidence-index-details dt {
    color: var(--fde-muted);
    font-size: 0.7rem;
    line-height: 1.4;
}
.evidence-index-details dd {
    color: var(--fde-text);
    font-size: 0.86rem;
    line-height: 1.55;
    margin-top: 0.12rem;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}
.evidence-index-dimensions {
    display: grid;
    gap: 0.12rem 0.65rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    list-style: none;
    margin: 0;
    padding: 0;
}
.evidence-index-dimensions li {
    min-width: 0;
    overflow-wrap: anywhere;
}
[class*="st-key-conclusion_evidence_actions_"] [data-testid="stHorizontalBlock"] {
    display: grid;
    gap: 0.45rem;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}
[class*="st-key-conclusion_evidence_actions_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    min-width: 0;
    width: auto !important;
}
[class*="st-key-conclusion_evidence_actions_"] .stButton > button {
    min-height: 44px;
    white-space: normal;
}
@media (max-width: 760px) {
    .stApp .block-container {
        min-width: 0;
        padding-bottom: max(5.5rem, env(safe-area-inset-bottom));
    }
    .report-masthead {
        margin: 0.4rem 0 1rem;
        padding: 0.85rem 0 0.95rem;
    }
    .report-masthead-title,
    [data-testid="stMarkdownContainer"] .report-masthead-title {
        font-size: 1.8rem !important;
        line-height: 1.16 !important;
        padding: 0 !important;
    }
    .report-masthead-description {
        font-size: 0.92rem;
        line-height: 1.55;
        margin-top: 0.55rem;
    }
    .report-masthead,
    .report-ledger,
    .report-section,
    .report-index,
    .evidence-index {
        min-width: 0;
    }
    .report-ledger {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .report-ledger-item:nth-child(2n) {
        border-right: 0;
        padding-left: 0.85rem;
    }
    .report-ledger-item:nth-child(2n + 1) {
        border-top: 1px solid var(--fde-line);
        padding-left: 0;
    }
    .report-ledger-item:nth-child(-n + 2) {
        border-top: 0;
    }
    .report-section-heading {
        gap: 0.3rem;
        grid-template-columns: minmax(0, 1fr);
    }
    .report-section-index {
        border-bottom: 1px solid var(--fde-line);
        padding: 0 0 0.3rem;
    }
    .report-section-body {
        margin-left: 0;
    }
    .report-index-row--header {
        display: none;
    }
    .report-index-row {
        grid-auto-columns: auto;
        grid-auto-flow: row;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .conclusion-model-index .report-index-row {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .st-key-conclusion_model_index [class*="st-key-conclusion_model_action_"] .stButton > button {
        min-height: 44px;
        white-space: normal;
        width: 100%;
    }
    .report-index-cell {
        padding: 0.55rem 0.45rem;
    }
    .report-index-cell::before {
        color: var(--fde-muted);
        content: attr(data-label);
        display: block;
        font-size: 0.68rem;
        letter-spacing: 0.04em;
        line-height: 1.35;
        margin-bottom: 0.12rem;
    }
    .report-index-cell:nth-child(odd) {
        padding-left: 0;
    }
    .evidence-index-item {
        gap: 0.55rem;
        grid-template-columns: 0.45rem minmax(0, 1fr);
    }
    .evidence-index-head,
    .evidence-index-details,
    .evidence-index-dimensions {
        min-width: 0;
    }
    .evidence-index-details,
    .evidence-index-dimensions {
        grid-template-columns: minmax(0, 1fr);
    }
    .evidence-index-content,
    .evidence-index-details dd,
    .evidence-index-dimensions li {
        overflow-wrap: anywhere;
    }
    .report-section button,
    .report-index button,
    .evidence-index button {
        min-height: 44px;
    }
    .stApp [data-testid="stDialog"] [role="dialog"] {
        max-height: calc(100dvh - 5.5rem - env(safe-area-inset-bottom));
        overflow-y: auto;
    }
}
"""
