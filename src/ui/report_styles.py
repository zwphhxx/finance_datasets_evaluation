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
.report-contents {
    border-bottom: 1px solid var(--fde-line);
    margin: 0 0 1.75rem;
    padding: 0 0 0.8rem;
}
.report-contents-label {
    color: var(--fde-muted);
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    margin: 0 0 0.5rem;
}
.report-contents-list {
    display: grid;
    gap: 0.4rem 1.1rem;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    list-style: none;
    margin: 0;
    padding: 0;
}
.report-contents-item a {
    color: var(--fde-ink);
    display: grid;
    font-size: 0.88rem;
    gap: 0.4rem;
    grid-template-columns: 1.65rem minmax(0, 1fr);
    line-height: 1.45;
    text-decoration: none;
}
.report-contents-item a:hover,
.report-contents-item a:focus-visible {
    color: var(--fde-gold);
    text-decoration: underline;
    text-underline-offset: 0.2rem;
}
.report-contents-item span {
    color: var(--fde-gold);
    font-family: var(--fde-serif);
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
.report-method-copy {
    max-width: 52rem;
}
.report-method-copy p {
    font-size: 0.96rem;
    line-height: 1.78;
    margin: 0 0 0.78rem;
}
.report-method-copy .report-method-lead {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1.04rem;
    font-weight: 650;
    line-height: 1.62;
    margin-bottom: 1rem;
}
.report-method-process {
    border-bottom: 1px solid var(--fde-line);
    border-top: 1px solid var(--fde-line);
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    list-style: none;
    margin: 1rem 0 0;
    padding: 0;
}
.report-method-process li {
    border-right: 1px solid var(--fde-line);
    font-size: 0.82rem;
    line-height: 1.5;
    min-width: 0;
    padding: 0.65rem 0.75rem;
}
.report-method-process li:last-child {
    border-right: 0;
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
.sample-report-index .report-index-row {
    grid-auto-flow: initial;
    grid-template-columns:
        minmax(5.5rem, 0.72fr)
        minmax(12rem, 2.25fr)
        minmax(6.5rem, 0.9fr)
        minmax(6rem, 0.8fr)
        minmax(5.5rem, 0.72fr);
}
.st-key-samples_index [class*="st-key-samples_index_row_"] {
    border-bottom: 1px solid var(--fde-line);
    min-width: 0;
    padding: 0.12rem 0;
}
.st-key-samples_index [class*="st-key-samples_index_row_"] .report-index-row {
    border-bottom: 0;
}
.st-key-samples_index [class*="st-key-samples_index_row_"] .stButton > button {
    min-height: 2.25rem;
    white-space: normal;
}
.sample-archive-panel {
    min-width: 0;
    padding: 0.35rem 0 0.25rem;
}
.sample-archive-panel .sample-detail-section {
    border-top: 1px solid var(--fde-line);
    margin-top: 0.85rem;
    padding-top: 0.85rem;
}
.sample-archive-panel .sample-detail-section:first-child {
    border-top: 0;
    margin-top: 0;
    padding-top: 0;
}
.st-key-conclusion_model_selector_mobile_region {
    display: none;
}
.st-key-conclusion_model_selector_desktop_region {
    border-bottom: 1px solid var(--fde-line-strong);
    margin-top: 0.2rem;
}
.st-key-conclusion_model_selector_desktop [role="radiogroup"] {
    align-items: stretch;
    display: flex;
    flex-wrap: nowrap;
    gap: 0 1.6rem;
    overflow-x: auto;
}
.st-key-conclusion_model_selector_desktop [data-baseweb="radio"] {
    border-bottom: 2px solid transparent;
    color: var(--fde-muted);
    min-height: 44px;
    padding: 0.72rem 0 0.55rem;
}
.st-key-conclusion_model_selector_desktop [data-baseweb="radio"]:has(input:checked) {
    border-bottom-color: var(--fde-gold);
    color: var(--fde-ink);
    font-weight: 650;
}
.st-key-conclusion_model_selector_desktop [data-baseweb="radio"] > div:first-child {
    display: none;
}
.evidence-review-context {
    align-items: baseline;
    border-bottom: 1px solid var(--fde-line);
    display: grid;
    gap: 0.35rem 1rem;
    grid-template-columns: auto minmax(8rem, 1fr) auto minmax(12rem, 1.4fr);
    margin-bottom: 1rem;
    padding: 0.8rem 0;
}
.evidence-review-context-label {
    color: var(--fde-muted);
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.06em;
}
.evidence-review-context strong {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1.1rem;
}
.evidence-review-context span:not(.evidence-review-context-label) {
    color: var(--fde-text);
    font-size: 0.9rem;
}
.st-key-conclusion_evidence_selector > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] {
    display: grid;
    gap: 0;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}
.st-key-conclusion_evidence_selector > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    min-width: 0;
    width: auto !important;
}
[class*="st-key-conclusion_evidence_choice_"] {
    border-bottom: 1px solid var(--fde-line);
    border-top: 1px solid var(--fde-line-strong);
    min-width: 0;
    padding: 0.75rem 0.8rem 0.45rem;
}
[class*="st-key-conclusion_evidence_choice_"]:has(.evidence-selector-item--active) {
    border-top: 2px solid var(--fde-gold);
    padding-top: calc(0.75rem - 1px);
}
.evidence-selector-item {
    min-height: 8.4rem;
    min-width: 0;
}
.evidence-selector-reason,
.evidence-selector-meta,
.evidence-selector-title {
    margin: 0;
}
.evidence-selector-reason {
    color: var(--fde-gold);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    line-height: 1.4;
}
.evidence-selector-meta {
    align-items: baseline;
    display: flex;
    justify-content: space-between;
    margin-top: 0.3rem;
}
.evidence-selector-meta strong {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1rem;
}
.evidence-selector-meta span {
    color: var(--fde-text);
    font-size: 0.86rem;
}
.evidence-selector-title {
    color: var(--fde-text);
    font-size: 0.88rem;
    line-height: 1.5;
    margin-top: 0.45rem;
    overflow-wrap: anywhere;
}
[class*="st-key-conclusion_evidence_choice_"] .stButton > button {
    min-height: 44px;
    overflow-wrap: anywhere;
    white-space: normal;
}
[class*="st-key-conclusion_selected_evidence_"] {
    margin-top: 1.2rem;
}
.st-key-conclusion_evidence_open_action {
    border-bottom: 1px solid var(--fde-line-strong);
    display: flex;
    justify-content: flex-end;
    padding: 0.15rem 0 0.85rem;
}
.st-key-conclusion_evidence_open_action .stButton > button {
    min-height: 44px;
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
    font-size: 0.95rem;
    line-height: 1.45;
    overflow-wrap: anywhere;
}
.evidence-index-case {
    color: var(--fde-gold);
    font-family: var(--fde-serif);
    font-weight: 700;
}
.evidence-index-model {
    color: var(--fde-ink);
    font-weight: 600;
}
.evidence-index-reason {
    color: var(--fde-ink);
    font-weight: 650;
}
.evidence-index-title,
[data-testid="stMarkdownContainer"] .evidence-index-title {
    color: var(--fde-ink);
    font-family: var(--fde-serif);
    font-size: 1.45rem !important;
    font-weight: 650;
    line-height: 1.38 !important;
    margin: 0.5rem 0 0;
    overflow-wrap: anywhere;
    padding: 0 !important;
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
    font-size: 0.82rem;
    line-height: 1.4;
}
.evidence-index-details dd {
    color: var(--fde-text);
    font-size: 1rem;
    line-height: 1.55;
    margin-top: 0.12rem;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}
.evidence-index-total-value {
    color: var(--fde-ink) !important;
    font-family: var(--fde-serif);
    font-size: 1.45rem !important;
    font-weight: 650;
    line-height: 1.3 !important;
}
.evidence-index-weakest-value {
    color: var(--fde-ink) !important;
    font-size: 1.08rem !important;
    font-weight: 650;
}
.evidence-index-dimension-detail {
    grid-column: 1 / -1;
}
.evidence-index-dimensions {
    display: grid;
    gap: 0.35rem 0.75rem;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    list-style: none;
    margin: 0;
    padding: 0;
}
.evidence-index-dimensions li {
    font-size: 0.98rem;
    line-height: 1.5;
    min-width: 0;
    overflow-wrap: anywhere;
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
    .report-contents,
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
    .report-section {
        margin-top: 1.2rem;
        padding-top: 0.9rem;
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
    .report-contents-list,
    .report-method-process {
        grid-template-columns: minmax(0, 1fr);
    }
    .report-contents-item a {
        min-height: 44px;
        padding: 0.38rem 0;
    }
    .report-method-process li {
        border-bottom: 1px solid var(--fde-line);
        border-right: 0;
    }
    .report-method-process li:last-child {
        border-bottom: 0;
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
    .sample-report-index .report-index-row {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .sample-report-index .report-index-cell:nth-child(1) {
        grid-column: 1;
        grid-row: 1;
    }
    .sample-report-index .report-index-cell:nth-child(2) {
        grid-column: 1 / -1;
        grid-row: 2;
    }
    .sample-report-index .report-index-cell:nth-child(3) {
        grid-column: 1;
        grid-row: 3;
    }
    .sample-report-index .report-index-cell:nth-child(4) {
        grid-column: 2;
        grid-row: 1;
    }
    .sample-report-index .report-index-cell:nth-child(5) {
        grid-column: 2;
        grid-row: 3;
    }
    .st-key-samples_index > [data-testid="stVerticalBlock"] {
        min-width: 0;
    }
    .st-key-samples_index [class*="st-key-samples_index_row_"] [data-testid="stHorizontalBlock"] {
        align-items: stretch;
        display: grid;
        gap: 0.2rem;
        grid-template-columns: minmax(0, 1fr);
        min-width: 0;
    }
    .st-key-samples_index [class*="st-key-samples_index_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: none !important;
        min-width: 0;
        width: 100% !important;
    }
    .st-key-samples_index [class*="st-key-samples_index_row_"] .stButton > button {
        min-height: 44px;
        overflow-wrap: anywhere;
        width: 100%;
    }
    .conclusion-model-index .report-index-cell:nth-child(4) .report-index-value {
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
        display: -webkit-box;
        overflow: hidden;
    }
    .report-index-cell {
        padding: 0.3rem 0.35rem;
    }
    .report-index-cell::before {
        color: var(--fde-muted);
        content: attr(data-label);
        display: block;
        font-size: 0.75rem;
        letter-spacing: 0.02em;
        line-height: 1.35;
        margin-bottom: 0.12rem;
    }
    .sample-report-index .report-index-cell {
        padding: 0.1rem 0.35rem;
    }
    .sample-report-index .report-index-cell::before {
        line-height: 1.2;
        margin-bottom: 0;
    }
    .sample-report-index .report-index-value {
        font-size: 0.9rem;
        line-height: 1.3;
    }
    .report-index-cell:nth-child(odd) {
        padding-left: 0;
    }
    .st-key-conclusion_model_selector_desktop_region {
        display: none;
    }
    .st-key-conclusion_model_selector_mobile_region {
        display: block;
    }
    .st-key-conclusion_model_selector_mobile [data-baseweb="select"] > div {
        min-height: 44px;
    }
    .evidence-review-context {
        gap: 0.25rem 0.7rem;
        grid-template-columns: auto minmax(0, 1fr);
        margin-bottom: 0.8rem;
        padding: 0.65rem 0;
    }
    .evidence-review-context span:not(.evidence-review-context-label) {
        font-size: 0.82rem;
    }
    .st-key-conclusion_evidence_selector > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] {
        grid-template-columns: minmax(0, 1fr);
    }
    [class*="st-key-conclusion_evidence_choice_"] {
        padding: 0.65rem 0 0.35rem;
    }
    [class*="st-key-conclusion_evidence_choice_"]:has(.evidence-selector-item--active) {
        padding-top: calc(0.65rem - 1px);
    }
    .evidence-selector-item {
        min-height: 0;
    }
    .evidence-selector-title {
        display: block;
        overflow: visible;
    }
    .st-key-conclusion_evidence_open_action .stButton,
    .st-key-conclusion_evidence_open_action .stButton > button {
        min-height: 44px;
        width: 100%;
    }
    .evidence-index-item {
        gap: 0.55rem;
        grid-template-columns: 0.45rem minmax(0, 1fr);
    }
    .evidence-index-title,
    [data-testid="stMarkdownContainer"] .evidence-index-title {
        font-size: 1.35rem !important;
        line-height: 1.38 !important;
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
