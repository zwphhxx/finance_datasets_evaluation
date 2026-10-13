"""Shared responsive styles for the Streamlit user interface."""

MOBILE_RESPONSIVE_CSS = r"""
/* Keep the native dialog frame and close control visible while its body scrolls.
   Use semantic attributes rather than Streamlit's generated class names. */
[data-testid="stDialog"] [role="dialog"] {
    display: flex;
    flex-direction: column;
    max-height: calc(100dvh - 6rem - env(safe-area-inset-bottom));
    overflow: hidden;
}
[data-testid="stDialog"] [role="dialog"] > div:has(> [data-testid="stVerticalBlock"]) {
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
}
[data-testid="stDialog"] [role="dialog"] > button[aria-label="Close"] {
    min-width: 44px;
    min-height: 44px;
    top: 0.75rem;
    right: 0.75rem;
}
.st-key-test_run_scope_actions {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

@media (min-width: 761px) and (max-width: 860px) {
    .block-container {
        max-width: 100%;
        padding-left: 1.1rem;
        padding-right: 1.1rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        overflow-x: auto;
        scrollbar-width: thin;
    }
}

@media (max-width: 760px) {
    .stApp {
        overflow-x: clip;
    }
    .block-container {
        box-sizing: border-box;
        max-width: 100%;
        overflow-x: clip;
        padding-left: 0.875rem;
        padding-right: 0.875rem;
        padding-bottom: calc(4.5rem + env(safe-area-inset-bottom));
    }
    .executive-takeaway {
        font-size: 1.05rem;
        margin-bottom: 1rem;
        padding-left: 0.75rem;
        width: 100%;
    }
    .st-key-samples_filter_region,
    .st-key-samples_list_region,
    .st-key-samples_detail_region,
    .st-key-test_run_stage_configuration,
    .st-key-test_run_stage_answers {
        box-sizing: border-box;
        min-width: 0;
        width: 100%;
    }
    .st-key-samples_filter_region [data-testid="stHorizontalBlock"] {
        align-items: stretch;
        flex-direction: column;
        gap: 0.55rem;
    }
    .st-key-samples_filter_region [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        min-width: 0;
        width: 100% !important;
    }
    .st-key-samples_title_bar [data-testid="stHorizontalBlock"] {
        display: grid;
        gap: 0.55rem;
        grid-template-columns: 1fr;
        width: 100%;
    }
    .st-key-samples_title_bar [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 0 0 auto !important;
        min-width: 0;
        width: auto !important;
    }
    .st-key-samples_title_bar [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
        width: 100% !important;
    }
    .st-key-samples_title_bar [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) {
        justify-self: end;
    }
    .st-key-samples_title_bar .stButton > button {
        min-height: 44px;
        padding-bottom: 0.25rem;
        padding-top: 0.25rem;
    }
    .st-key-samples_title_bar [data-testid="stPopover"] button,
    .st-key-conclusion_maintenance_entry [data-testid="stPopover"] button,
    .st-key-test_run_maintenance_entry [data-testid="stPopover"] button,
    .st-key-samples_detail_region [data-testid="stPopover"] button {
        min-height: 44px !important;
    }
    .st-key-samples_detail_region [role="tab"],
    .st-key-samples_detail_region [data-baseweb="tab"] {
        min-height: 44px !important;
    }
    .st-key-conclusion_data_notice [data-testid="stHorizontalBlock"] {
        align-items: center;
        display: grid;
        gap: 0.55rem;
        grid-template-columns: 1fr max-content;
        width: 100%;
    }
    .st-key-conclusion_data_notice [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 0 0 auto !important;
        min-width: 0;
        width: auto !important;
    }
    .st-key-conclusion_data_notice .stButton > button {
        min-height: 44px;
        width: auto;
    }
    button[kind="elementToolbar"] {
        min-height: 44px;
        min-width: 44px;
    }
    .st-key-test_run_scope_actions {
        gap: 0.55rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .block-container [data-testid="stLayoutWrapper"]:has(> [data-testid="stHorizontalBlock"] .top-nav-brand) {
        position: sticky;
        top: 0;
        z-index: 50;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        align-items: center;
        background: var(--fde-bg);
        border-bottom: 1px solid var(--fde-line);
        box-sizing: border-box;
        display: grid;
        gap: 0.4rem;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        margin: 0 -0.875rem;
        max-width: none;
        padding: 0.45rem 0.875rem 0.55rem;
        position: static;
        top: 0;
        width: 100vw;
        z-index: auto;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        > [data-testid="stColumn"] {
        flex: 0 0 auto !important;
        min-width: 0;
        width: 100% !important;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        > [data-testid="stColumn"]:first-child {
        grid-column: 1 / 3;
        grid-row: 1;
        min-width: 0;
        width: 100% !important;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        > [data-testid="stColumn"]:nth-child(2) {
        grid-column: 1 / -1;
        grid-row: 2;
        width: 100% !important;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        > [data-testid="stColumn"]:nth-child(3) {
        grid-column: 3;
        grid-row: 1;
        justify-self: end;
        width: auto !important;
    }
    .st-key-top_nav_review_region [data-testid="stHorizontalBlock"] {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        width: 100%;
    }
    .st-key-top_nav_review_region [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 0 0 auto !important;
        min-width: 0;
        width: 100% !important;
    }
    .st-key-top_nav_operation_region .stButton {
        justify-content: flex-end !important;
    }
    .st-key-top_nav_operation_region .stButton > button,
    .st-key-top_nav_operation_region [data-testid="stPopover"] > button {
        min-height: 44px;
        width: auto !important;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
        justify-content: center;
        width: 100%;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button {
        justify-content: center;
        min-height: 44px;
        padding-left: 0.65rem;
        padding-right: 0.65rem;
        width: 100%;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        .stButton > button[kind="secondary"]::after {
        bottom: 0.1rem;
        left: 0.65rem;
        right: 0.65rem;
    }
    [data-testid="stMarkdownContainer"] .page-title-heading {
        font-size: 1.5rem;
    }
    .page-title-copy {
        font-size: 0.9rem;
    }
    .section-heading-page {
        align-items: baseline;
        column-gap: 0.65rem;
        grid-template-columns: 2.5rem minmax(0, 1fr);
        margin: 0.85rem 0 0.65rem;
        padding-top: 0.65rem;
    }
    [id^="fde-"] {
        scroll-margin-top: 5.75rem;
    }
    .detail-panel-body,
    .sample-detail-panel-body {
        padding: 0.75rem 0.8rem 0.85rem;
    }
    .markdown-detail-body,
    .document-text,
    .sample-detail-text,
    .sample-detail-list {
        min-width: 0;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    .markdown-detail-code,
    .markdown-detail-table-scroll {
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    .sample-detail-table-wrap {
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    .markdown-detail-table {
        min-width: 36rem;
    }
    [data-testid="stDataFrame"] {
        /* The native grid owns horizontal scrolling; an outer scroll container
           adds a second bar and can clip the final column in Safari. */
        max-width: 100%;
        min-width: 0;
    }
    [data-testid="stDialog"] [role="dialog"] {
        box-sizing: border-box;
        max-height: calc(100dvh - 5.5rem - env(safe-area-inset-bottom));
        max-width: calc(100vw - 24px);
        overflow-x: hidden;
        overflow-y: hidden;
        width: calc(100vw - 24px);
    }
    [data-testid="stDialog"] [role="dialog"] > div:has(> [data-testid="stVerticalBlock"]) {
        padding-bottom: calc(5.25rem + env(safe-area-inset-bottom));
    }
    [data-testid="stDialog"] [role="dialog"] [data-testid="stHorizontalBlock"] {
        align-items: stretch;
        flex-direction: column;
        gap: 0.55rem;
        width: 100%;
    }
    [data-testid="stDialog"] [role="dialog"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        min-width: 0;
        width: 100% !important;
    }
    .st-key-test_run_sample_table {
        max-width: 100%;
        overflow-x: hidden;
    }
    .st-key-test_run_sample_table_header {
        display: none;
    }
    [class*="st-key-test_run_sample_row_"] {
        border-bottom: 1px solid var(--fde-line);
        padding: 0.55rem 0;
    }
    [class*="st-key-test_run_sample_row_"]:last-child {
        border-bottom: 0;
    }
    [class*="st-key-test_run_sample_row_"] [data-testid="stHorizontalBlock"] {
        align-items: start;
        display: grid !important;
        gap: 0.12rem 0.55rem;
        grid-template-columns: 2.5rem minmax(0, 1fr) minmax(0, 1fr);
        min-width: 0;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: none !important;
        min-width: 0;
        width: auto !important;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) {
        grid-column: 1;
        grid-row: 1 / 4;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) {
        grid-column: 2;
        grid-row: 1;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) {
        grid-column: 2 / 4;
        grid-row: 2;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) {
        grid-column: 2;
        grid-row: 3;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(5) {
        grid-column: 3;
        grid-row: 3;
    }
    [class*="st-key-test_run_sample_row_"]
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(6) {
        grid-column: 3;
        grid-row: 1;
    }
    [data-testid="stDialog"] .st-key-test_run_sample_dialog_actions,
    [data-testid="stDialog"] .st-key-test_run_model_dialog_actions,
    [data-testid="stDialog"] .st-key-test_run_prompt_dialog_actions {
        background: var(--fde-surface);
        bottom: calc(1.25rem + env(safe-area-inset-bottom));
        box-sizing: border-box;
        left: 2.25rem;
        margin-top: 0.5rem;
        padding: 0.6rem 0 0.25rem;
        position: fixed;
        right: 2.25rem;
        width: auto !important;
        z-index: 1002;
    }
    [data-testid="stDialog"] .st-key-test_run_sample_dialog_actions [data-testid="stHorizontalBlock"],
    [data-testid="stDialog"] .st-key-test_run_model_dialog_actions [data-testid="stHorizontalBlock"] {
        display: grid !important;
        flex-direction: row;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    [data-testid="stDialog"] .st-key-test_run_sample_dialog_actions [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    [data-testid="stDialog"] .st-key-test_run_model_dialog_actions [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: none !important;
        min-width: 0;
        width: auto !important;
    }
    [data-testid="stDialog"] .st-key-test_run_sample_dialog_actions .stButton > button,
    [data-testid="stDialog"] .st-key-test_run_model_dialog_actions .stButton > button,
    [data-testid="stDialog"] .st-key-test_run_prompt_dialog_actions .stButton > button {
        min-height: 44px;
        width: 100%;
    }
    .st-key-test_run_primary_action .stButton > button {
        min-height: 44px;
        width: 100%;
    }
    .st-key-test_run_primary_action .stButton,
    .st-key-test_run_primary_action {
        width: 100%;
    }
    .stButton > button,
    .stDownloadButton > button,
    .stFormSubmitButton > button {
        min-height: 44px;
    }
}

@media (max-width: 480px) {
    .block-container {
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        margin-left: -0.75rem;
        margin-right: -0.75rem;
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }
    .top-nav-brand {
        font-size: 0.86rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button {
        font-size: 0.82rem;
        padding-left: 0.2rem;
        padding-right: 0.2rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .st-key-top_nav_operation_region .stButton > button {
        font-size: 0.78rem;
        font-weight: 500;
    }
    .section-heading-page .section-heading-title {
        font-size: 1.08rem;
    }
    .inline-status {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

/* Owned container keys isolate the evidence layout from unrelated controls. */
[class*="st-key-score_detail_"] { min-width: 0; }
[class*="st-key-score_detail_"] [data-testid="stHorizontalBlock"] {
    flex-direction: row-reverse;
    align-items: flex-start;
}
[class*="st-key-score_detail_"] [data-testid="stText"] {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    line-height: 1.7;
}
[data-testid="stMetricValue"], .report-ledger dd { font-variant-numeric: tabular-nums; }
.run-stages { display: flex; gap: 0.6rem; padding: 0; margin: 1rem 0; list-style: none; }
.run-stages li { flex: 1; border-bottom: 2px solid var(--fde-line); padding: 0.55rem 0; color: var(--fde-muted); font-size: 0.85rem; }
.run-stages li[aria-current="step"] { color: var(--fde-accent); border-color: var(--fde-accent); font-weight: 650; }
@media (max-width: 860px) {
    [class*="st-key-score_detail_"] [data-testid="stHorizontalBlock"],
    .st-key-workbench_filters [data-testid="stHorizontalBlock"],
    .st-key-review_filters [data-testid="stHorizontalBlock"] { flex-direction: column; gap: 1rem; }
    [class*="st-key-score_detail_"] [data-testid="stColumn"],
    .st-key-workbench_filters [data-testid="stColumn"],
    .st-key-review_filters [data-testid="stColumn"] { width: 100% !important; flex: 1 1 100% !important; min-width: 0; }
    .run-stages li { font-size: 0.78rem; overflow-wrap: anywhere; }
}
"""
