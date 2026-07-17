"""Shared responsive styles for the Streamlit user interface."""

MOBILE_RESPONSIVE_CSS = r"""
.st-key-test_run_actions {
    display: grid;
    gap: 1rem;
    grid-template-columns: 1fr 1fr 1.2fr;
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
    .st-key-samples_title_bar [data-testid="stHorizontalBlock"] {
        align-items: stretch;
        flex-direction: column;
        gap: 0.55rem;
        width: 100%;
    }
    .st-key-samples_title_bar
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        min-width: 0;
        width: 100% !important;
    }
    .st-key-test_run_actions {
        gap: 0.55rem;
        grid-template-columns: 1fr;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        align-items: center;
        background: color-mix(in srgb, var(--fde-bg) 92%, transparent);
        border-bottom: 1px solid var(--fde-line);
        box-sizing: border-box;
        display: grid;
        gap: 0.4rem;
        grid-template-columns: repeat(4, max-content);
        margin: 0 -0.875rem;
        max-width: none;
        overflow-x: auto;
        padding: 0.45rem 0.875rem 0.55rem;
        position: sticky;
        scrollbar-width: thin;
        top: 0;
        width: 100vw;
        z-index: 50;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        > [data-testid="stColumn"] {
        flex: 0 0 auto !important;
        min-width: max-content;
        width: auto !important;
    }
    .block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)
        > [data-testid="stColumn"]:first-child {
        grid-column: 1 / -1;
        min-width: 0;
        width: 100% !important;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
        justify-content: flex-start;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button {
        justify-content: flex-start;
        min-height: 44px;
        padding-left: 0.65rem;
        padding-right: 0.65rem;
    }
    [data-testid="stMarkdownContainer"] .page-title-heading {
        font-size: 1.3rem;
    }
    [data-testid="stMarkdownContainer"] .brief-title {
        font-size: 1.78rem;
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
    .home-section {
        margin-top: 1.75rem;
        padding-top: 1.2rem;
    }
    .home-section-first {
        margin-top: 1.25rem;
        padding-top: 0;
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
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    [data-testid="stDialog"] [role="dialog"] {
        box-sizing: border-box;
        max-height: calc(100dvh - 24px);
        max-width: calc(100vw - 24px);
        overflow-x: hidden;
        overflow-y: auto;
        width: calc(100vw - 24px);
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
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    .st-key-test_run_sample_table > div,
    .st-key-test_run_sample_table [data-testid="stHorizontalBlock"] {
        min-width: 44rem;
    }
    .st-key-test_run_sample_table [data-testid="stHorizontalBlock"] {
        display: grid;
        grid-template-columns: 3rem 6rem minmax(15rem, 2.6fr) 6rem 4.5rem 5.5rem;
    }
    .st-key-test_run_sample_table
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        min-width: 0;
        width: auto !important;
    }
    .st-key-test_run_answer_viewer {
        gap: 0.7rem;
    }
    .st-key-test_run_run {
        background: var(--fde-bg);
        border-top: 1px solid var(--fde-line);
        bottom: 0;
        box-shadow: 0 -8px 20px color-mix(in srgb, var(--fde-ink) 12%, transparent);
        box-sizing: border-box;
        left: 0;
        padding: 0.65rem 0.875rem calc(0.65rem + env(safe-area-inset-bottom));
        position: fixed;
        right: 0;
        width: 100vw;
        z-index: 45;
    }
    .st-key-test_run_run .stButton > button {
        min-height: 44px;
        width: 100%;
    }
    .st-key-test_run_run .stButton {
        width: 100%;
    }
    .st-key-test_run_run:has(button:disabled),
    .stApp:has(.st-key-test_run_answer_viewer) .st-key-test_run_run {
        background: transparent;
        border-top: 0;
        box-shadow: none;
        left: auto;
        padding: 0;
        position: static;
        right: auto;
        width: 100%;
    }
    .stApp:has(.st-key-test_run_run:not(:has(button:disabled))) .block-container {
        padding-bottom: calc(6.75rem + env(safe-area-inset-bottom));
    }
    .stApp:has(.st-key-test_run_answer_viewer) .block-container {
        padding-bottom: calc(4.5rem + env(safe-area-inset-bottom));
    }
    body:has([data-testid="stDialog"]) .st-key-test_run_run {
        visibility: hidden;
    }
    .stApp:has(input:focus) .st-key-test_run_run,
    .stApp:has(textarea:focus) .st-key-test_run_run {
        background: transparent;
        border-top: 0;
        box-shadow: none;
        left: auto;
        padding: 0;
        position: static;
        right: auto;
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
    [data-testid="stMarkdownContainer"] .brief-title {
        font-size: 1.6rem;
    }
    .section-heading-page .section-heading-title {
        font-size: 1.08rem;
    }
    .inline-status {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
"""
