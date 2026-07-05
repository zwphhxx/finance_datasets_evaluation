from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st


STYLE_CSS = """
<style>
:root {
    --fde-bg: #f6f7f9;
    --fde-surface: #ffffff;
    --fde-surface-muted: #eef1f5;
    --fde-line: #e1e5ec;
    --fde-line-strong: #cfd6e1;
    --fde-text: #1f2733;
    --fde-ink: #263241;
    --fde-muted: #6a7686;
    --fde-blue: #2b4a6f;
    --fde-blue-soft: #eaf0f7;
    --fde-blue-border: #d3deec;
    /* Low-saturation status palette: error = rose, warning = beige, improve = sage. */
    --fde-red: #8a3a3a;
    --fde-red-soft: #f6e9ea;
    --fde-red-border: #e3cdcd;
    --fde-orange: #7c5a30;
    --fde-orange-soft: #f2ecdf;
    --fde-orange-border: #e0d4ba;
    --fde-green: #2f5d3f;
    --fde-green-soft: #e9f0ea;
    --fde-green-border: #cdddd0;
    --fde-gray-soft: #f1f3f6;
    --fde-status-neutral-bg: #f4f5f7;
    --fde-status-neutral-border: #dde2ea;
    --fde-status-neutral-text: #4f5b6a;
    --fde-status-muted-bg: #f8f9fb;
    --fde-status-muted-border: #e5e8ee;
    --fde-status-muted-text: #6a7686;
    --fde-status-success-bg: #edf3ef;
    --fde-status-success-border: #d6e2d9;
    --fde-status-success-text: #2f5d3f;
    --fde-status-warning-bg: #f5f0e7;
    --fde-status-warning-border: #e4d9c6;
    --fde-status-warning-text: #6f5430;
    --fde-status-danger-bg: #f5ecec;
    --fde-status-danger-border: #e1d1d1;
    --fde-status-danger-text: #7a3f3f;
    --fde-shadow: 0 0 0 transparent;
    /* Portfolio aliases: a single accent + shared radius/spacing scale so the
       case-study layer stays consistent with the existing design system. */
    --fde-accent: #2b4a6f;
    --fde-radius: 12px;
    --fde-radius-lg: 18px;
    --fde-space: 1rem;
    /* Portfolio template tokens (PR-UI6) */
    --portfolio-bg-start: #f0f4f8;
    --portfolio-bg-end: #f7f9fb;
    --portfolio-text: #1a1a1a;
    --portfolio-muted: #6b7280;
    --portfolio-accent-green: #2f5d3f;
    --portfolio-line: #e5e7eb;
    --portfolio-max-width: 1120px;
}
.stApp {
    background: linear-gradient(180deg, var(--portfolio-bg-start) 0%, var(--portfolio-bg-end) 100%);
    color: var(--fde-text);
}
#MainMenu,
footer,
header,
[data-testid="stDeployButton"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stToolbar"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}
.block-container {
    padding-top: 1.05rem;
    padding-bottom: 3rem;
    max-width: var(--portfolio-max-width);
    margin: 0 auto;
}
[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid var(--fde-line);
}
/* Top nav bar styling */
.top-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.15rem 0 0.45rem 0;
    border-bottom: 1px solid var(--fde-line);
    background: transparent;
    position: sticky;
    top: 0;
    z-index: 100;
    margin: 0 0 0.35rem 0;
}
.top-nav-kicker {
    color: var(--fde-ink);
    font-size: 0.82rem;
    font-weight: 760;
    letter-spacing: 0.02em;
    white-space: nowrap;
}
.top-nav-flow {
    color: var(--fde-muted);
    font-size: 0.78rem;
    white-space: nowrap;
}
.top-nav-links {
    display: flex;
    gap: 0.25rem;
    flex-wrap: wrap;
}
.top-nav-link {
    display: inline-block;
    padding: 0.4rem 0.85rem;
    font-size: 0.88rem;
    font-weight: 650;
    color: var(--portfolio-muted);
    text-decoration: none;
    border-radius: 8px;
    transition: all 0.15s ease;
    cursor: pointer;
    border: none;
    background: transparent;
}
.top-nav-link:hover,
.top-nav-link.active {
    color: var(--portfolio-text);
    background: var(--fde-surface-muted);
}
.top-nav-link.active {
    font-weight: 750;
}
@media (max-width: 768px) {
    .top-nav { flex-wrap: wrap; padding: 0.2rem 0 0.35rem 0; }
    .top-nav-kicker { font-size: 0.8rem; }
    .top-nav-flow { display: none; }
    .top-nav-link { padding: 0.3rem 0.6rem; font-size: 0.82rem; }
}
.top-nav .stButton > button,
[data-testid="stMarkdownContainer"]:has(.top-nav) + div[data-testid="stHorizontalBlock"] .stButton > button {
    min-height: 2.15rem;
    padding: 0.34rem 0.4rem;
    border-radius: 0;
    border: 0;
    border-bottom: 2px solid transparent;
    background: transparent;
    color: var(--fde-muted);
    font-size: 0.9rem;
    font-weight: 650;
    box-shadow: none;
}
.top-nav .stButton > button[kind="secondary"],
[data-testid="stMarkdownContainer"]:has(.top-nav) + div[data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"] {
    border: 1px solid var(--fde-line);
    border-bottom: 2px solid var(--fde-ink);
    background: #ffffff;
    color: var(--fde-ink);
    font-weight: 760;
}
.top-nav .stButton > button:hover,
[data-testid="stMarkdownContainer"]:has(.top-nav) + div[data-testid="stHorizontalBlock"] .stButton > button:hover {
    border-bottom-color: var(--fde-line-strong);
    background: var(--fde-status-muted-bg);
    color: var(--fde-ink);
}
.nav-brand {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 0.9rem 1rem;
    margin: 0.25rem 0 1rem 0;
}
.nav-brand-title {
    color: var(--fde-blue);
    font-size: 1.05rem;
    font-weight: 800;
    letter-spacing: 0.02em;
}
.nav-brand-subtitle {
    color: var(--fde-muted);
    font-size: 0.82rem;
    line-height: 1.45;
    margin-top: 0.28rem;
}
[data-testid="stSidebar"] .stButton > button {
    width: 100%;
    justify-content: flex-start;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    background: transparent;
    color: var(--fde-text);
    border-radius: 9px;
    padding: 0.62rem 0.8rem;
    font-weight: 650;
    box-shadow: none;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--fde-blue-soft);
    border-color: var(--fde-blue-border);
    border-left: 3px solid var(--fde-blue);
    color: var(--fde-blue);
    font-weight: 750;
}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] .stButton > button:focus {
    background: var(--fde-surface-muted);
    color: var(--fde-blue);
    border-color: transparent;
    border-left-color: var(--fde-line);
}
.stButton > button,
[data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
    border-radius: 8px;
    min-height: 2.25rem;
    padding: 0.42rem 0.82rem;
    font-weight: 680;
    box-shadow: none;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.stButton > button[kind="primary"],
[data-testid="stFormSubmitButton"] button[kind="primary"],
[data-testid="stDownloadButton"] button[kind="primary"] {
    background: var(--fde-blue);
    border: 1px solid var(--fde-blue);
    color: #ffffff;
}
.stButton > button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
[data-testid="stDownloadButton"] button[kind="primary"]:hover {
    background: var(--fde-ink);
    border-color: var(--fde-ink);
    color: #ffffff;
}
.stButton > button[kind="secondary"],
[data-testid="stFormSubmitButton"] button[kind="secondary"],
[data-testid="stDownloadButton"] button[kind="secondary"] {
    background: #ffffff;
    border: 1px solid var(--fde-line-strong);
    color: var(--fde-ink);
}
.stButton > button[kind="secondary"]:hover,
[data-testid="stFormSubmitButton"] button[kind="secondary"]:hover,
[data-testid="stDownloadButton"] button[kind="secondary"]:hover {
    background: var(--fde-surface-muted);
    border-color: var(--fde-line-strong);
    color: var(--fde-ink);
}
.stButton > button[kind="tertiary"],
[data-testid="stFormSubmitButton"] button[kind="tertiary"],
[data-testid="stDownloadButton"] button[kind="tertiary"] {
    background: transparent;
    border: 1px solid transparent;
    color: var(--fde-muted);
    min-height: 1.9rem;
    padding: 0.22rem 0.46rem;
    font-size: 0.82rem;
}
.stButton > button[kind="tertiary"]:hover,
[data-testid="stFormSubmitButton"] button[kind="tertiary"]:hover,
[data-testid="stDownloadButton"] button[kind="tertiary"]:hover {
    background: var(--fde-status-muted-bg);
    border-color: var(--fde-line);
    color: var(--fde-ink);
}
.page-header {
    border: 1px solid var(--fde-line);
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-surface);
    border-radius: 12px;
    padding: 0.95rem 1.15rem;
    margin-bottom: 0.7rem;
    box-shadow: var(--fde-shadow);
}
.page-eyebrow {
    color: var(--fde-muted);
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.3rem;
}
.page-header h1 {
    color: var(--fde-blue);
    font-size: 1.55rem;
    line-height: 1.2;
    margin: 0 0 0.35rem 0;
}
.page-header p {
    color: var(--fde-muted);
    margin: 0.15rem 0;
    font-size: 0.95rem;
}
.boundary-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    align-items: center;
    margin: 0 0 1rem 0;
}
.boundary-chip {
    display: inline-block;
    background: var(--fde-surface-muted);
    color: var(--fde-muted);
    border: 1px solid var(--fde-line);
    border-radius: 999px;
    padding: 0.16rem 0.66rem;
    font-size: 0.78rem;
    font-weight: 600;
}
.metric-card,
.fde-card,
.info-panel,
.warning-panel,
.empty-state,
.model-answer-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1rem;
    margin: 0.45rem 0;
    box-shadow: var(--fde-shadow);
}
.metric-card .metric-label,
.metric-help,
.section-caption,
.panel-content,
.empty-state {
    color: var(--fde-muted);
}
.metric-card .metric-value {
    color: var(--fde-blue);
    font-size: 1.65rem;
    font-weight: 750;
    line-height: 1.25;
}
.info-panel {
    background: var(--fde-surface);
    border-left: 3px solid var(--fde-blue);
}
.context-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.75rem;
    margin: 0.65rem 0 1rem 0;
}
.context-item {
    border: 1px solid var(--fde-line);
    background: #ffffff;
    border-radius: 12px;
    padding: 0.85rem 0.95rem;
}
.context-label {
    color: var(--fde-blue);
    font-size: 0.86rem;
    font-weight: 750;
    margin-bottom: 0.35rem;
}
.context-copy {
    color: var(--fde-muted);
    font-size: 0.94rem;
    line-height: 1.55;
}
.warning-panel {
    border-color: var(--fde-orange-border);
    background: var(--fde-orange-soft);
    color: var(--fde-orange);
}
.empty-state {
    background: var(--fde-gray-soft);
    text-align: center;
}
.section-title {
    margin-top: 1.2rem;
    margin-bottom: 0.45rem;
}
.section-title h3 {
    color: var(--fde-blue);
    margin-bottom: 0.15rem;
}
.score-badge,
.status-badge {
    display: inline-block;
    border-radius: 999px;
    padding: 0.14rem 0.52rem;
    font-size: 0.8rem;
    font-weight: 650;
    border: 1px solid transparent;
}
.score-high,
.status-success {
    background: var(--fde-status-success-bg);
    color: var(--fde-status-success-text);
    border-color: var(--fde-status-success-border);
}
.score-mid,
.status-warning,
.status-medium {
    background: var(--fde-status-warning-bg);
    color: var(--fde-status-warning-text);
    border-color: var(--fde-status-warning-border);
}
.score-low,
.status-danger,
.status-high {
    background: var(--fde-status-danger-bg);
    color: var(--fde-status-danger-text);
    border-color: var(--fde-status-danger-border);
}
.status-neutral {
    background: var(--fde-status-neutral-bg);
    color: var(--fde-status-neutral-text);
    border-color: var(--fde-status-neutral-border);
}
.status-low {
    background: var(--fde-status-neutral-bg);
    color: var(--fde-status-neutral-text);
    border-color: var(--fde-status-neutral-border);
}
.status-muted {
    background: var(--fde-status-muted-bg);
    color: var(--fde-status-muted-text);
    border-color: var(--fde-status-muted-border);
}
.score-neutral {
    background: var(--fde-status-neutral-bg);
    color: var(--fde-status-neutral-text);
    border-color: var(--fde-status-neutral-border);
}
.model-answer-card h4 {
    margin: 0 0 0.35rem 0;
    color: var(--fde-blue);
}
.model-answer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    color: var(--fde-blue);
    margin-bottom: 0.35rem;
}
.model-answer-meta {
    color: var(--fde-muted);
    font-size: 0.9rem;
    margin-bottom: 0.6rem;
}
.model-answer-text,
.comparison-answer,
.model-answer-note p {
    color: var(--fde-text);
    line-height: 1.65;
}
.model-answer-note {
    border-top: 1px solid var(--fde-line);
    margin-top: 0.85rem;
    padding-top: 0.75rem;
}
.answer-boundary-panel {
    border: 1px solid var(--fde-blue-border);
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-blue-soft);
    border-radius: 12px;
    padding: 1rem;
    margin: 0.65rem 0 1rem 0;
}
.answer-boundary-panel h4,
.comparison-card h4 {
    color: var(--fde-blue);
    margin: 0 0 0.5rem 0;
}
.boundary-row {
    border-top: 1px solid var(--fde-line);
    padding: 0.55rem 0;
}
.boundary-row:first-of-type {
    border-top: none;
}
.boundary-label,
.comparison-meta {
    color: var(--fde-muted);
    font-size: 0.84rem;
    font-weight: 700;
}
.boundary-value,
.comparison-body {
    color: var(--fde-text);
    line-height: 1.6;
    margin-top: 0.18rem;
}
.comparison-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 0.85rem;
    margin-top: 0.7rem;
}
.comparison-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: #ffffff;
    padding: 1rem;
}
.comparison-card-preferred {
    border-left: 3px solid var(--fde-green);
}
.comparison-card-rejected {
    border-left: 3px solid var(--fde-orange);
}
.comparison-label {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 750;
    letter-spacing: 0.04em;
    margin-bottom: 0.3rem;
}
.loop-rail {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(128px, 1fr);
    overflow-x: auto;
    gap: 0.65rem;
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: #ffffff;
    padding: 0.85rem;
    margin: 0.5rem 0 1rem 0;
}
.loop-step {
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-blue-soft);
    border-radius: 10px;
    padding: 0.7rem 0.75rem;
    min-height: 4.3rem;
}
.loop-step-index {
    color: var(--fde-muted);
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.04em;
}
.loop-step-label {
    color: var(--fde-blue);
    font-weight: 750;
    margin-top: 0.25rem;
}
.task-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1.05rem 1.15rem;
    margin: 0.55rem 0;
    box-shadow: var(--fde-shadow);
}
.task-card-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
}
.task-card-id {
    color: var(--fde-blue);
    font-weight: 800;
    font-size: 1.02rem;
    letter-spacing: 0.02em;
}
.task-card-badges {
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
}
.task-card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0.55rem 0 0.2rem 0;
}
.tag {
    display: inline-block;
    border-radius: 999px;
    padding: 0.16rem 0.62rem;
    font-size: 0.8rem;
    font-weight: 700;
    border: 1px solid transparent;
}
.tag-domain {
    background: var(--fde-blue-soft);
    color: var(--fde-blue);
    border-color: var(--fde-blue-border);
}
.tag-type {
    background: var(--fde-gray-soft);
    color: var(--fde-muted);
    border-color: var(--fde-line);
}
.task-card-field {
    margin-top: 0.6rem;
}
.task-card-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.15rem;
}
.task-card-value {
    color: var(--fde-text);
    line-height: 1.6;
}
[data-testid="stSelectbox"] label {
    color: var(--fde-muted);
    font-weight: 700;
    font-size: 0.82rem;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    border-radius: 12px;
    border-color: var(--fde-line);
    background: #ffffff;
}
.fact-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1rem 1.1rem;
    margin: 0.45rem 0;
    box-shadow: var(--fde-shadow);
}
.fact-field {
    margin-top: 0.65rem;
}
.fact-field:first-child {
    margin-top: 0;
}
.fact-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.15rem;
}
.fact-value {
    color: var(--fde-text);
    line-height: 1.62;
}
.boundary-list {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    margin: 0.3rem 0 0.2rem 0;
}
.redline-item {
    border: 1px solid var(--fde-red-border);
    border-left: 3px solid var(--fde-red);
    background: var(--fde-red-soft);
    color: var(--fde-red);
    border-radius: 10px;
    padding: 0.5rem 0.72rem;
    font-size: 0.92rem;
    line-height: 1.5;
}
.point-item {
    border: 1px solid var(--fde-green-border);
    border-left: 3px solid var(--fde-green);
    background: var(--fde-green-soft);
    color: var(--fde-green);
    border-radius: 10px;
    padding: 0.5rem 0.72rem;
    font-size: 0.92rem;
    line-height: 1.5;
}
.rubric-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.4rem 0 0.6rem 0;
    font-size: 0.92rem;
}
.rubric-table thead th {
    text-align: left;
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 750;
    padding: 0.5rem 0.6rem;
    border-bottom: 1px solid var(--fde-line);
}
.rubric-table td {
    padding: 0.6rem;
    border-bottom: 1px solid var(--fde-line);
    color: var(--fde-text);
    vertical-align: top;
}
.rubric-dim {
    font-weight: 750;
    color: var(--fde-blue);
    white-space: nowrap;
}
.rubric-score {
    font-weight: 800;
    color: var(--fde-blue);
    white-space: nowrap;
}
.rubric-gap {
    color: var(--fde-muted);
    white-space: nowrap;
}
.rubric-evidence {
    color: var(--fde-muted);
    line-height: 1.55;
}
.evidence-card {
    border: 1px solid var(--fde-line);
    border-radius: 8px;
    background: var(--fde-surface);
    padding: 0.85rem 0.95rem;
    margin: 0.4rem 0;
    box-shadow: var(--fde-shadow);
}
.evidence-card-clean {
    border-left: 3px solid var(--fde-green);
}
.evidence-card-flagged {
    border-left: 3px solid var(--fde-red);
}
.evidence-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.35rem;
}
.evidence-title {
    color: var(--fde-blue);
    font-weight: 750;
}
.evidence-field {
    margin-top: 0.55rem;
}
.evidence-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.12rem;
}
.evidence-value {
    color: var(--fde-text);
    line-height: 1.6;
}
.matrix-table,
.check-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.4rem 0 0.4rem 0;
    font-size: 0.9rem;
}
.matrix-table th,
.matrix-table td {
    border: 1px solid var(--fde-line);
    padding: 0.5rem 0.6rem;
    text-align: center;
}
.matrix-table thead th {
    background: var(--fde-surface-muted);
    color: var(--fde-muted);
    font-weight: 750;
}
.matrix-table tbody th {
    background: var(--fde-blue-soft);
    color: var(--fde-blue);
    font-weight: 750;
    text-align: left;
    white-space: nowrap;
}
.matrix-table td {
    color: var(--fde-text);
}
.matrix-zero {
    color: var(--fde-muted);
}
.matrix-total {
    background: var(--fde-gray-soft);
    font-weight: 750;
    color: var(--fde-blue);
}
.check-table td,
.check-table th {
    padding: 0.6rem;
    border-bottom: 1px solid var(--fde-line);
    text-align: left;
    vertical-align: top;
}
.check-table thead th {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 750;
}
.check-table .check-key {
    color: var(--fde-blue);
    font-weight: 750;
    white-space: nowrap;
}
.check-table .check-count {
    font-weight: 800;
    color: var(--fde-blue);
    white-space: nowrap;
}
.check-table .check-note {
    color: var(--fde-muted);
    line-height: 1.55;
}
.stDataFrame,
[data-testid="stDataFrame"] {
    border: 1px solid var(--fde-line);
    border-radius: 8px;
    overflow: hidden;
    background: #ffffff;
}
[data-testid="stDataFrame"] [role="columnheader"] {
    background: #f7f8fa;
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 650;
}
[data-testid="stDataFrame"] [role="gridcell"] {
    color: var(--fde-text);
    font-size: 0.84rem;
}
[data-testid="stDataFrame"] [role="gridcell"]:first-child {
    color: var(--fde-ink);
    font-weight: 720;
}
/* Redline verdict banner: a single low-saturation statement strip. */
.redline-verdict {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    border: 1px solid var(--fde-blue-border);
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-blue-soft);
    border-radius: 12px;
    padding: 0.8rem 1.1rem;
    margin: 0.15rem 0 1.1rem 0;
    box-shadow: var(--fde-shadow);
}
.redline-verdict-badge {
    flex: 0 0 auto;
    background: var(--fde-red-soft);
    color: var(--fde-red);
    border: 1px solid var(--fde-red-border);
    border-radius: 999px;
    padding: 0.2rem 0.66rem;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    white-space: nowrap;
}
.redline-verdict-text {
    color: var(--fde-text);
    font-weight: 700;
    font-size: 1rem;
    line-height: 1.5;
}
.redline-verdict-text .accent {
    color: var(--fde-red);
}
/* Boundary cards: three usage tiers, count-first, low-saturation top accent. */
.boundary-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 0.8rem;
    margin: 0.5rem 0 1rem 0;
}
.boundary-card {
    border: 1px solid var(--fde-line);
    border-top: 3px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1rem 1.05rem;
    box-shadow: var(--fde-shadow);
}
.boundary-card-direct {
    border-top-color: var(--fde-green);
}
.boundary-card-review {
    border-top-color: var(--fde-orange);
}
.boundary-card-not_direct {
    border-top-color: var(--fde-red);
}
.boundary-card-title {
    color: var(--fde-blue);
    font-weight: 750;
    font-size: 0.95rem;
    margin-bottom: 0.4rem;
}
.boundary-card-count {
    font-size: 1.9rem;
    font-weight: 800;
    line-height: 1.1;
    color: var(--fde-blue);
}
.boundary-card-direct .boundary-card-count {
    color: var(--fde-green);
}
.boundary-card-review .boundary-card-count {
    color: var(--fde-orange);
}
.boundary-card-not_direct .boundary-card-count {
    color: var(--fde-red);
}
.boundary-card-unit {
    font-size: 0.85rem;
    color: var(--fde-muted);
    font-weight: 650;
    margin-left: 0.3rem;
}
.boundary-card-desc {
    color: var(--fde-muted);
    font-size: 0.86rem;
    line-height: 1.55;
    margin-top: 0.45rem;
}
.boundary-card-meta {
    color: var(--fde-text);
    font-size: 0.82rem;
    line-height: 1.5;
    margin-top: 0.45rem;
    padding-top: 0.45rem;
    border-top: 1px solid var(--fde-line);
}
/* Horizontal evaluation-loop flow with arrows between nodes. */
.flow-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 0.35rem;
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: #ffffff;
    padding: 0.85rem;
    margin: 0.5rem 0 1rem 0;
    box-shadow: var(--fde-shadow);
}
.flow-node {
    flex: 1 1 auto;
    min-width: 92px;
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-blue-soft);
    border-radius: 9px;
    padding: 0.55rem 0.6rem;
}
.flow-node-index {
    color: var(--fde-muted);
    font-size: 0.7rem;
    font-weight: 750;
    letter-spacing: 0.04em;
}
.flow-node-label {
    color: var(--fde-blue);
    font-weight: 750;
    font-size: 0.9rem;
    margin-top: 0.2rem;
}
.flow-arrow {
    align-self: center;
    color: var(--fde-muted);
    font-weight: 700;
}
/* Redline verdict card: the headline judgement on a single case + model. */
.verdict-card {
    border: 1px solid var(--fde-line);
    border-left: 4px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1rem 1.15rem;
    margin: 0.4rem 0 0.9rem 0;
    box-shadow: var(--fde-shadow);
}
.verdict-card-direct {
    border-left-color: var(--fde-green);
}
.verdict-card-review {
    border-left-color: var(--fde-orange);
}
.verdict-card-not_direct {
    border-left-color: var(--fde-red);
}
.verdict-card-none {
    border-left-color: var(--fde-line);
}
.verdict-head {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    margin-bottom: 0.5rem;
}
.verdict-score {
    color: var(--fde-muted);
    font-weight: 700;
    font-size: 0.9rem;
}
.verdict-reason {
    color: var(--fde-text);
    line-height: 1.6;
    font-weight: 650;
}
.verdict-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 0.7rem;
    margin-top: 0.7rem;
    padding-top: 0.7rem;
    border-top: 1px solid var(--fde-line);
}
.verdict-field-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 750;
    margin-bottom: 0.25rem;
}
.verdict-field-value {
    color: var(--fde-text);
    line-height: 1.55;
}
.fingerprint-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(248px, 1fr));
    gap: 0.85rem;
    margin: 0.4rem 0 0.3rem;
}
.fingerprint-card {
    background: var(--fde-surface);
    border: 1px solid var(--fde-blue-border);
    border-top: 3px solid var(--fde-muted);
    border-radius: 10px;
    padding: 0.95rem 1rem 0.85rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
}
.fingerprint-card-success { border-top-color: var(--fde-green); }
.fingerprint-card-warning { border-top-color: var(--fde-orange); }
.fingerprint-card-danger { border-top-color: var(--fde-red); }
.fingerprint-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
}
.fingerprint-model {
    font-weight: 800;
    color: var(--fde-blue);
    font-size: 1rem;
    word-break: break-all;
}
.fingerprint-score {
    font-weight: 800;
    font-size: 1.45rem;
    color: var(--fde-text);
    line-height: 1;
    white-space: nowrap;
}
.fingerprint-score small {
    display: block;
    font-size: 0.68rem;
    font-weight: 650;
    color: var(--fde-muted);
    text-align: right;
    margin-top: 0.15rem;
}
.fingerprint-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.32rem;
}
.fingerprint-list li {
    display: flex;
    justify-content: space-between;
    gap: 0.6rem;
    font-size: 0.86rem;
    line-height: 1.45;
}
.fingerprint-list li span {
    color: var(--fde-muted);
    flex: 0 0 auto;
}
.fingerprint-list li b {
    color: var(--fde-text);
    font-weight: 700;
    text-align: right;
}
.fingerprint-list li.fingerprint-redline b {
    color: var(--fde-red);
}
.fingerprint-note {
    margin: 0;
    color: var(--fde-muted);
    font-size: 0.78rem;
    line-height: 1.5;
    border-top: 1px dashed var(--fde-blue-border);
    padding-top: 0.5rem;
}
/* -------------------------------------------------------------------------- */
/* Portfolio case-study layer: hero, numbered sections, feature / case cards.  */
/* Adds visual language (big title, wide whitespace, sectioned narrative) on    */
/* top of the existing component palette without replacing any class above.     */
/* -------------------------------------------------------------------------- */
.fde-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr);
    gap: 1.25rem;
    align-items: center;
    border: 0;
    border-left: 3px solid var(--fde-line-strong);
    border-radius: 0;
    background: transparent;
    padding: 1rem 0 1rem 1.05rem;
    margin: 0.6rem 0 1rem 0;
    box-shadow: var(--fde-shadow);
}
.fde-hero-eyebrow {
    color: var(--fde-muted);
    font-size: 0.74rem;
    font-weight: 750;
    letter-spacing: 0.04em;
    margin-bottom: 0.45rem;
}
.fde-hero-title {
    color: var(--fde-ink);
    font-size: 2.1rem;
    font-weight: 800;
    line-height: 1.08;
    letter-spacing: 0;
    margin: 0 0 0.55rem 0;
}
.fde-hero-subtitle {
    color: var(--fde-text);
    font-size: 1.12rem;
    line-height: 1.55;
    font-weight: 650;
    margin: 0 0 0.65rem 0;
}
.fde-hero-value {
    color: var(--fde-muted);
    font-size: 0.98rem;
    line-height: 1.62;
    margin: 0;
}
.fde-hero-aside {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
    gap: 0.55rem;
}
.fde-hero-stat {
    border: 1px solid var(--fde-line);
    border-left: 2px solid var(--fde-line-strong);
    background: var(--fde-surface);
    border-radius: 8px;
    padding: 0.72rem 0.8rem;
}
.fde-hero-stat-value {
    color: var(--fde-ink);
    font-size: 1.45rem;
    font-weight: 800;
    line-height: 1.05;
}
.fde-hero-stat-label {
    color: var(--fde-muted);
    font-size: 0.82rem;
    margin-top: 0.25rem;
    line-height: 1.4;
}
@media (max-width: 820px) {
    .fde-hero { grid-template-columns: 1fr; padding: 0.9rem 0 0.9rem 0.9rem; }
    .fde-hero-title { font-size: 1.7rem; }
}
.section-block {
    display: flex;
    align-items: flex-start;
    gap: 0.7rem;
    margin: 1.35rem 0 0.55rem 0;
}
.section-block-index {
    flex: 0 0 auto;
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    border-left: 2px solid var(--fde-line-strong);
    background: transparent;
    border-radius: 0;
    padding: 0.08rem 0 0.08rem 0.45rem;
    line-height: 1.4;
}
.section-block-body { flex: 1 1 auto; min-width: 0; }
.section-block-title {
    color: var(--fde-ink);
    font-size: 1.08rem;
    font-weight: 800;
    line-height: 1.25;
    margin: 0;
}
.section-block-desc {
    color: var(--fde-muted);
    font-size: 0.92rem;
    line-height: 1.5;
    margin-top: 0.2rem;
}
.feature-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(228px, 1fr));
    gap: 0.8rem;
    margin: 0.6rem 0 1rem 0;
}
.feature-card {
    border: 1px solid var(--fde-line);
    border-top: 3px solid var(--fde-blue);
    background: var(--fde-surface);
    border-radius: var(--fde-radius);
    padding: 1rem 1.05rem;
    box-shadow: var(--fde-shadow);
}
.feature-card-title {
    color: var(--fde-blue);
    font-weight: 800;
    font-size: 0.98rem;
    margin-bottom: 0.35rem;
}
.feature-card-body {
    color: var(--fde-muted);
    font-size: 0.93rem;
    line-height: 1.58;
}
.case-study-card {
    border: 1px solid var(--fde-line);
    border-left: 4px solid var(--fde-blue);
    background: var(--fde-surface);
    border-radius: 14px;
    padding: 1.15rem 1.25rem;
    margin: 0.55rem 0 1rem 0;
    box-shadow: var(--fde-shadow);
}
.case-study-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
}
.case-study-title {
    color: var(--fde-blue);
    font-weight: 800;
    font-size: 1.08rem;
}
.case-study-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
}
.case-study-summary {
    color: var(--fde-text);
    line-height: 1.62;
    margin-top: 0.55rem;
}
.case-study-metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
    gap: 0.65rem;
    margin-top: 0.8rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--fde-line);
}
.case-study-metric-value {
    color: var(--fde-blue);
    font-weight: 800;
    font-size: 1.25rem;
    line-height: 1.1;
}
.case-study-metric-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    margin-top: 0.2rem;
}
.status-pill {
    display: inline-block;
    border-radius: 999px;
    padding: 0.14rem 0.56rem;
    font-size: 0.78rem;
    font-weight: 650;
    border: 1px solid transparent;
}
.status-pill-neutral { background: var(--fde-gray-soft); color: var(--fde-muted); border-color: var(--fde-line); }
.status-pill-success { background: var(--fde-green-soft); color: var(--fde-green); border-color: var(--fde-green-border); }
.status-pill-warning { background: var(--fde-orange-soft); color: var(--fde-orange); border-color: var(--fde-orange-border); }
.status-pill-danger { background: var(--fde-red-soft); color: var(--fde-red); border-color: var(--fde-red-border); }
.status-pill-accent { background: var(--fde-blue-soft); color: var(--fde-blue); border-color: var(--fde-blue-border); }
.cta-note {
    color: var(--fde-muted);
    font-size: 0.84rem;
    line-height: 1.5;
    margin: 0.15rem 0 0.4rem 0;
}
/* -------------------------------------------------------------------------- */
/* PR-UI6 Portfolio template: new hero, mockup, checklist, story components  */
/* -------------------------------------------------------------------------- */
.portfolio-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    gap: 2.5rem;
    align-items: start;
    padding: 2.5rem 0 3rem 0;
    margin: 0 0 1rem 0;
}
@media (max-width: 820px) {
    .portfolio-hero { grid-template-columns: 1fr; gap: 1.5rem; padding: 1.5rem 0 2rem 0; }
}
.portfolio-hero-main {
    min-width: 0;
}
.portfolio-hero-title {
    color: var(--portfolio-text);
    font-size: 3.6rem;
    font-weight: 900;
    line-height: 1.05;
    letter-spacing: 0;
    margin: 0 0 0.6rem 0;
}
@media (max-width: 820px) {
    .portfolio-hero-title { font-size: 2.4rem; }
}
.portfolio-hero-subtitle {
    color: var(--portfolio-text);
    font-size: 1.25rem;
    font-weight: 700;
    line-height: 1.5;
    margin: 0 0 0.8rem 0;
}
.portfolio-hero-desc {
    color: var(--portfolio-muted);
    font-size: 1.05rem;
    line-height: 1.7;
    margin: 0 0 1.2rem 0;
}
.portfolio-checklist {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin: 0 0 1.2rem 0;
}
.portfolio-checklist-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--portfolio-accent-green);
    font-size: 0.98rem;
    font-weight: 650;
    line-height: 1.5;
}
.check-symbol {
    color: var(--portfolio-accent-green);
    font-weight: 700;
    font-size: 1rem;
}
.portfolio-meta-line {
    color: var(--portfolio-muted);
    font-size: 0.88rem;
    line-height: 1.6;
    margin: 0;
}
.portfolio-hero-mockups {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    align-items: center;
    padding-top: 1rem;
}
.mockup-desktop {
    width: 100%;
    max-width: 360px;
    height: 220px;
    border: 1px solid var(--portfolio-line);
    border-radius: 10px;
    background: #ffffff;
    padding: 0.6rem 0.7rem;
    box-shadow: var(--fde-shadow);
    display: flex;
    flex-direction: column;
}
.mockup-mobile {
    width: 100%;
    max-width: 160px;
    height: 280px;
    border: 1px solid var(--portfolio-line);
    border-radius: 14px;
    background: #ffffff;
    padding: 0.5rem 0.55rem;
    box-shadow: 0 4px 20px rgba(0,0,0,0.06);
    display: flex;
    flex-direction: column;
}
.mockup-topbar {
    display: flex;
    gap: 0.3rem;
    margin-bottom: 0.4rem;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid var(--portfolio-line);
}
.mockup-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--portfolio-line);
}
.mockup-nav {
    display: flex;
    gap: 0.35rem;
    margin-bottom: 0.5rem;
}
.mockup-nav-item {
    height: 6px;
    border-radius: 3px;
    background: var(--portfolio-line);
}
.mockup-nav-item:first-child {
    width: 24px;
    background: var(--fde-blue);
}
.mockup-nav-item:nth-child(2) {
    width: 18px;
}
.mockup-nav-item:nth-child(3) {
    width: 14px;
}
.mockup-line {
    height: 5px;
    border-radius: 2px;
    background: var(--fde-surface-muted);
    margin-bottom: 0.35rem;
}
.mockup-line.short { width: 55%; }
.mockup-line.medium { width: 75%; }
.mockup-line.long { width: 95%; }
.mockup-line.highlight {
    background: var(--fde-blue-soft);
    height: 18px;
    margin: 0.4rem 0;
}
.mockup-stack {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    justify-content: center;
    flex-wrap: wrap;
}
@media (max-width: 820px) {
    .mockup-stack { flex-direction: column; align-items: center; }
}
/* Story section: two-column narrative layout */
.story-section {
    display: grid;
    grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
    gap: 2.5rem;
    align-items: start;
    padding: 2rem 0;
    border-top: 1px solid var(--portfolio-line);
    margin-top: 1rem;
}
@media (max-width: 820px) {
    .story-section { grid-template-columns: 1fr; gap: 1rem; padding: 1.5rem 0; }
}
.story-section-title {
    color: var(--portfolio-text);
    font-size: 1.6rem;
    font-weight: 800;
    line-height: 1.2;
    margin: 0 0 0.4rem 0;
}
.story-section-body {
    color: var(--portfolio-muted);
    font-size: 0.98rem;
    line-height: 1.75;
}
.story-section-body p {
    margin: 0 0 0.8rem 0;
}
/* Process line: horizontal narrative flow */
.process-line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
    margin: 0.6rem 0 1.2rem 0;
    padding: 0.5rem 0;
}
.process-node {
    display: inline-block;
    padding: 0.35rem 0.7rem;
    border-radius: 8px;
    background: var(--fde-surface);
    border: 1px solid var(--portfolio-line);
    font-size: 0.9rem;
    font-weight: 650;
    color: var(--portfolio-text);
    white-space: nowrap;
}
.process-arrow {
    color: var(--portfolio-muted);
    font-size: 0.85rem;
    font-weight: 700;
}
/* Tag cloud */
.tag-cloud {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin: 0.5rem 0 1rem 0;
}
.tag-cloud-item {
    display: inline-block;
    padding: 0.3rem 0.8rem;
    border-radius: 999px;
    background: var(--fde-surface);
    border: 1px solid var(--portfolio-line);
    font-size: 0.9rem;
    font-weight: 650;
    color: var(--portfolio-text);
}
/* Pull quote */
.pull-quote {
    border-left: 3px solid var(--fde-blue);
    padding: 0.6rem 1.2rem;
    margin: 1rem 0;
    color: var(--portfolio-text);
    font-size: 1.1rem;
    font-weight: 700;
    font-style: italic;
    line-height: 1.6;
}
/* Editorial list */
.editorial-list {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin: 0.5rem 0 1rem 0;
}
.editorial-item {
    display: flex;
    align-items: baseline;
    gap: 0.7rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--portfolio-line);
}
.editorial-item:last-child {
    border-bottom: none;
}
.editorial-item-name {
    font-weight: 750;
    color: var(--portfolio-text);
    font-size: 0.98rem;
    white-space: nowrap;
}
.editorial-item-judgment {
    color: var(--portfolio-muted);
    font-size: 0.94rem;
    line-height: 1.5;
    flex: 1;
}
.editorial-item-bar {
    display: flex;
    gap: 0.2rem;
    align-items: center;
}
.editorial-bar-segment {
    width: 20px;
    height: 4px;
    border-radius: 2px;
    background: var(--portfolio-line);
}
.editorial-bar-segment.filled {
    background: var(--fde-blue);
}
/* Evidence block: thin-bordered, minimal evidence container */
.evidence-block {
    border: 1px solid var(--portfolio-line);
    border-radius: 8px;
    background: var(--fde-surface);
    padding: 1rem 1.1rem;
    margin: 0.5rem 0;
}
.evidence-block-title {
    color: var(--portfolio-muted);
    font-size: 0.82rem;
    font-weight: 750;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
}
/* Conclusion list: minimal, no-card formal conclusions */
.conclusion-list {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    margin: 0.5rem 0 1rem 0;
}
.conclusion-item {
    padding: 0.8rem 0;
    border-bottom: 1px solid var(--portfolio-line);
}
.conclusion-item:last-child {
    border-bottom: none;
}
.conclusion-item-text {
    color: var(--portfolio-text);
    font-size: 1rem;
    line-height: 1.7;
    font-weight: 650;
}
.conclusion-item-meta {
    color: var(--portfolio-muted);
    font-size: 0.85rem;
    margin-top: 0.25rem;
}
/* CTA row: lightweight inline CTAs */
.cta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
    margin: 0.8rem 0 1.2rem 0;
}
.cta-link {
    display: inline-block;
    padding: 0.4rem 0.9rem;
    border-radius: 8px;
    background: var(--fde-surface);
    border: 1px solid var(--portfolio-line);
    font-size: 0.92rem;
    font-weight: 700;
    color: var(--fde-blue);
    text-decoration: none;
    cursor: pointer;
    transition: all 0.15s ease;
}
.cta-link:hover {
    background: var(--fde-blue-soft);
    border-color: var(--fde-blue-border);
}
/* -------------------------------------------------------------------------- */
/* Clean, low-card layout helpers (UI refinement pass).                        */
/* Used to reduce card walls and improve information hierarchy.               */
/* -------------------------------------------------------------------------- */
.kv-list {
    display: grid;
    grid-template-columns: minmax(90px, auto) 1fr;
    gap: 0.35rem 0.9rem;
    font-size: 0.94rem;
    line-height: 1.55;
    margin: 0.4rem 0 0.9rem 0;
}
.kv-list dt {
    color: var(--fde-muted);
    font-weight: 700;
    font-size: 0.82rem;
}
.kv-list dd {
    color: var(--fde-text);
    margin: 0;
}
.text-block {
    margin: 0.4rem 0 0.9rem 0;
}
.asset-section {
    border-top: 1px solid var(--fde-line);
    padding-top: 0.65rem;
    margin: 0.35rem 0 0.9rem 0;
}
.asset-section .check-note {
    color: var(--fde-muted);
    font-size: 0.88rem;
    line-height: 1.55;
    margin: 0.2rem 0 0.65rem 0;
}
.review-risk-note {
    border: 1px solid var(--fde-status-neutral-border);
    border-left: 3px solid var(--fde-status-neutral-text);
    background: #ffffff;
    border-radius: 8px;
    padding: 0.72rem 0.9rem;
    margin: 0.45rem 0 0.8rem 0;
    color: var(--fde-text);
}
.review-risk-note strong {
    display: block;
    color: var(--fde-text);
    font-size: 0.95rem;
    margin-bottom: 0.2rem;
}
.review-risk-note span,
.review-risk-note p {
    display: block;
    margin: 0.1rem 0 0 0;
    color: var(--fde-muted);
    font-size: 0.9rem;
    line-height: 1.55;
}
.review-risk-note ul {
    margin-top: 0.35rem;
}
.review-risk-note-success {
    border-color: var(--fde-status-success-border);
    border-left-color: var(--fde-status-success-text);
    background: #ffffff;
}
.review-risk-note-warning {
    border-color: var(--fde-status-warning-border);
    border-left-color: var(--fde-status-warning-text);
    background: #ffffff;
}
.review-risk-note-danger {
    border-color: var(--fde-status-danger-border);
    border-left-color: var(--fde-status-danger-text);
    background: #ffffff;
}
.review-risk-note-neutral,
.review-risk-note-muted {
    border-color: var(--fde-status-neutral-border);
    border-left-color: var(--fde-status-neutral-text);
    background: #ffffff;
}
.text-block-label {
    color: var(--fde-muted);
    font-size: 0.82rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
}
.text-block-body {
    color: var(--fde-text);
    font-size: 0.95rem;
    line-height: 1.65;
    white-space: pre-wrap;
}
.answer-viewer-summary {
    border: 1px solid var(--fde-line);
    border-radius: 8px;
    background: #ffffff;
    padding: 0.72rem 0.85rem;
    margin: 0.35rem 0 0.8rem 0;
}
.answer-viewer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
    gap: 0.55rem 0.9rem;
}
.answer-viewer-item span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.76rem;
    font-weight: 720;
    margin-bottom: 0.12rem;
}
.answer-viewer-item strong {
    display: block;
    color: var(--fde-text);
    font-size: 0.9rem;
    font-weight: 650;
    line-height: 1.45;
    overflow-wrap: anywhere;
}
.answer-viewer-muted {
    border-top: 1px solid var(--fde-line);
    color: var(--fde-muted);
    font-size: 0.82rem;
    line-height: 1.45;
    margin-top: 0.65rem;
    padding-top: 0.5rem;
    overflow-wrap: anywhere;
}
.two-col-panel {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 1.25rem;
    margin: 0.4rem 0 1rem 0;
}
@media (max-width: 820px) {
    .two-col-panel { grid-template-columns: 1fr; }
}
.two-col-panel .col {
    min-width: 0;
}
.inline-status {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem 1.2rem;
    font-size: 0.9rem;
    color: var(--fde-muted);
    margin: 0.3rem 0 0.9rem 0;
}
.inline-status strong {
    color: var(--fde-text);
    font-weight: 650;
}
.clean-list {
    list-style: none;
    margin: 0.4rem 0 0.9rem 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}
.clean-list li {
    position: relative;
    padding-left: 1.1rem;
    color: var(--fde-text);
    font-size: 0.94rem;
    line-height: 1.55;
}
.clean-list li::before {
    content: "•";
    position: absolute;
    left: 0;
    color: var(--fde-muted);
}
.clean-list-item {
    position: relative;
    padding-left: 1.1rem;
    color: var(--fde-text);
    font-size: 0.94rem;
    line-height: 1.55;
    margin: 0.35rem 0;
}
.clean-list-item::before {
    content: "•";
    position: absolute;
    left: 0;
    color: var(--fde-muted);
}
.clean-list-item.red::before {
    color: var(--fde-red);
}
</style>
"""


def render_html(html: str, container=None) -> None:
    """Render trusted internal HTML as a single Markdown HTML block.

    Streamlit renders Markdown, which treats a blank line as the end of an
    HTML block and any line indented four or more spaces as a code block.
    Multi-line f-string templates leak both: nested fragments keep their
    source indentation and join with blank lines, so Streamlit shows the raw
    tags as code. Stripping every line and dropping blanks collapses the
    template into one uninterrupted HTML block that always renders as markup.
    """
    target = container or st
    lines = [line.strip() for line in str(html).splitlines()]
    normalized = "\n".join(line for line in lines if line)
    target.markdown(normalized, unsafe_allow_html=True)


def apply_global_styles() -> None:
    render_html(STYLE_CSS)


def render_page_header(title: str, subtitle: str, boundary_note: str | None = None) -> None:
    """Render a consistent page header.

    boundary_note is kept for backward compatibility. The page-level data
    boundary is shown by render_context_summary to avoid duplicate top notes.
    """
    import streamlit as st

    safe_title = escape(str(title or ""))
    safe_subtitle = escape(str(subtitle or ""))
    render_html(
        f"""
        <div class="page-header">
            <div class="page-eyebrow">FinDueEval</div>
            <h1>{safe_title}</h1>
            <p>{safe_subtitle}</p>
        </div>
        """
    )


# Global, qualitative boundary disclaimer shown as a one-line chip strip under
# every page header. These are project-wide caveats about the demo's data nature
# (not business metrics, sample counts, model names or scores), so they stay a
# fixed constant rather than being read per-page.
GLOBAL_BOUNDARY_CHIPS = ["MVP 样本", "脱敏任务", "裁判建议分待复核", "仅用于样本内观察"]


def render_boundary_bar(chips=None) -> None:
    """Render the one-line boundary strip that replaces the old 3-card top."""
    items = chips if chips is not None else GLOBAL_BOUNDARY_CHIPS
    chip_html = "".join(f'<span class="boundary-chip">{escape(str(chip))}</span>' for chip in items)
    render_html(f'<div class="boundary-bar">{chip_html}</div>')


def render_page_shell(page_config) -> None:
    """Render the unified page title and a lightweight boundary bar."""
    render_page_header(page_config.title, page_config.subtitle)
    render_boundary_bar()


def render_card(content: str, class_name: str = "fde-card") -> None:
    render_html(f'<div class="{escape(str(class_name))}">{content}</div>')


def render_metric_card(label, value, help_text=None) -> None:
    help_html = f'<div class="metric-help">{escape(str(help_text))}</div>' if help_text else ""
    render_card(
        f"""
        <div class="metric-label">{escape(str(label))}</div>
        <div class="metric-value">{escape(str(value))}</div>
        {help_html}
        """,
        class_name="metric-card",
    )


def render_info_panel(title, content) -> None:
    render_html(
        f"""
        <div class="info-panel">
            <strong>{escape(str(title))}</strong>
            <div class="panel-content">{escape(str(content))}</div>
        </div>
        """
    )


def render_context_grid(items) -> None:
    item_html = []
    for label, copy in items:
        item_html.append(
            f"""
            <div class="context-item">
                <div class="context-label">{escape(str(label))}</div>
                <div class="context-copy">{escape(str(copy))}</div>
            </div>
            """
        )
    render_html(
        f'<div class="context-grid">{"".join(item_html)}</div>',
    )


def render_context_summary(context) -> None:
    render_context_grid(
        [
            ("本页回答什么问题", context.get("question", "")),
            ("当前数据边界", context.get("boundary", "")),
            ("页面核心看点", context.get("highlights", "")),
        ]
    )


def render_warning_panel(content) -> None:
    render_html(
        f'<div class="warning-panel">{escape(str(content))}</div>',
    )


def render_empty_state(message) -> None:
    render_html(
        f'<div class="empty-state">{escape(str(message))}</div>',
    )


def render_empty_state_with_actions(message: str, actions: list[tuple[str, str]]) -> None:
    """Render an empty state with call-to-action buttons.

    actions: list of (label, page_key) tuples. Each button navigates to the
    corresponding page when clicked.
    """
    import streamlit as st

    render_html(f'<div class="empty-state">{escape(message)}</div>')
    cols = st.columns(len(actions))
    for col, (label, page_key) in zip(cols, actions):
        with col:
            if st.button(label, key=f"empty_cta_{page_key}", use_container_width=True):
                st.session_state.current_page = page_key
                st.rerun()


def render_badge(text, level: str = "neutral", kind: str = "status") -> None:
    class_prefix = "score" if kind == "score" else "status"
    if class_prefix == "score":
        normalized_level = str(level).strip().lower()
        if normalized_level not in {"high", "mid", "low", "neutral"}:
            normalized_level = "neutral"
    else:
        normalized_level = _normalize_level(level)
    render_html(f'<span class="{class_prefix}-badge {class_prefix}-{normalized_level}">{escape(str(text))}</span>')


def render_status_badge(text, level) -> None:
    render_badge(text, str(level), kind="status")


def render_score_badge(score) -> None:
    score_text, level = _score_text_and_level(score)
    render_badge(score_text, level, kind="score")


def render_review_caveat(eval_status) -> None:
    """真实模式下，在展示评分的页面顶部提示：分数为裁判建议分，需人工复核。

    eval_status 为 app.py 注入 data_bundle 的字典；非真实运行时静默跳过。
    """
    if not isinstance(eval_status, dict) or not eval_status.get("live"):
        return
    scored = int(eval_status.get("scored", 0) or 0)
    confirmed = int(eval_status.get("confirmed", 0) or 0)
    render_html(
        '<div class="warning-panel">当前评分为裁判模型建议分（如未复核，请在总览页确认归档）。'
        f"已复核 {confirmed}/{scored}。</div>"
    )


def render_section_title(title, caption=None) -> None:
    caption_html = f'<div class="section-caption">{escape(str(caption))}</div>' if caption else ""
    render_html(
        f"""
        <div class="section-title">
            <h3>{escape(str(title))}</h3>
            {caption_html}
        </div>
        """
    )


def render_loop_rail(steps) -> None:
    step_html = []
    for index, step in enumerate(steps, start=1):
        step_html.append(
            f"""
            <div class="loop-step">
                <div class="loop-step-index">环节 {index:02d}</div>
                <div class="loop-step-label">{escape(str(step))}</div>
            </div>
            """
        )
    render_html(
        f'<div class="loop-rail">{"".join(step_html)}</div>',
    )


def render_redline_verdict(text: str, badge: str = "红线优先") -> None:
    """Render the single-statement verdict banner for the cockpit home.

    `text` may contain a `[[...]]` span which is highlighted in the accent color;
    everything else is escaped as plain text.
    """
    safe = escape(str(text))
    safe = safe.replace("[[", '<span class="accent">').replace("]]", "</span>")
    render_html(
        f"""
        <div class="redline-verdict">
            <span class="redline-verdict-badge">{escape(str(badge))}</span>
            <span class="redline-verdict-text">{safe}</span>
        </div>
        """
    )


def render_flow_strip(steps) -> None:
    """Render an emphasized horizontal flow with arrows between nodes."""
    parts: list[str] = []
    for index, step in enumerate(steps, start=1):
        if index > 1:
            parts.append('<span class="flow-arrow">→</span>')
        parts.append(
            f"""
            <div class="flow-node">
                <div class="flow-node-index">{index:02d}</div>
                <div class="flow-node-label">{escape(str(step))}</div>
            </div>
            """
        )
    render_html(f'<div class="flow-strip">{"".join(parts)}</div>')


def render_fingerprint_cards(cards) -> None:
    """Render one capability-fingerprint card per model.

    Each card expects the keys produced by ``build_model_fingerprints``: model,
    avg_score, strongest_dim, weakest_dim, top_error, redline_count, tendency,
    tendency_level, tendency_note. Levels reuse the shared status palette so the
    cards stay visually consistent with the rest of the design system.
    """
    blocks: list[str] = []
    for card in cards:
        level = str(card.get("tendency_level", "neutral"))
        rows = [
            ("最强维度", str(card.get("strongest_dim", "暂无")), False),
            ("最弱维度", str(card.get("weakest_dim", "暂无")), False),
            ("高频错误", str(card.get("top_error", "无")), False),
            ("红线错误", f'{int(card.get("redline_count", 0))} 次', True),
        ]
        items = "".join(
            f'<li class="fingerprint-redline"><span>{escape(label)}</span><b>{escape(value)}</b></li>'
            if is_redline
            else f'<li><span>{escape(label)}</span><b>{escape(value)}</b></li>'
            for label, value, is_redline in rows
        )
        blocks.append(
            f"""
            <div class="fingerprint-card fingerprint-card-{escape(level)}">
                <div class="fingerprint-head">
                    <span class="fingerprint-model">{escape(str(card.get("model", "")))}</span>
                    <span class="fingerprint-score">{float(card.get("avg_score", 0.0)):.1f}<small>平均总分</small></span>
                </div>
                <span class="status-badge status-{escape(level)}">{escape(str(card.get("tendency", "")))}</span>
                <ul class="fingerprint-list">{items}</ul>
                <p class="fingerprint-note">{escape(str(card.get("tendency_note", "")))}</p>
            </div>
            """
        )
    render_html(f'<div class="fingerprint-grid">{"".join(blocks)}</div>')


def render_model_answer_card(
    model_name: str,
    answer: object,
    score: object | None = None,
    review_note: object | None = None,
    meta: object | None = None,
) -> None:
    """Render a model answer card while preserving paragraph structure."""
    import streamlit as st

    def display_value(value: object, fallback: str = "暂无可展示数据") -> str:
        if value is None:
            return fallback
        text_value = str(value).strip()
        if not text_value or text_value.lower() in {"nan", "none", "null"}:
            return fallback
        return text_value

    safe_model = escape(display_value(model_name, "未标注模型"))
    safe_answer = escape(display_value(answer, "暂无回答内容。"))
    safe_answer = safe_answer.replace(chr(10), "<br>")
    score_text = display_value(score, "")
    meta_text = display_value(meta, "")
    review_text = display_value(review_note, "")
    safe_review = escape(review_text).replace(chr(10), "<br>") if review_text else ""

    score_html = f'<span class="score-badge">{escape(score_text)}</span>' if score_text else ""
    meta_html = f'<div class="model-answer-meta">{escape(meta_text)}</div>' if meta_text else ""
    review_html = (
        f'<div class="model-answer-note"><strong>扣分说明</strong><p>{safe_review}</p></div>'
        if safe_review
        else ""
    )

    render_html(
        f"""
        <div class="model-answer-card">
            <div class="model-answer-header">
                <strong>{safe_model}</strong>
                {score_html}
            </div>
            {meta_html}
            <div class="model-answer-text" style="white-space: pre-wrap; line-height: 1.65;">{safe_answer}</div>
            {review_html}
        </div>
        """
    )


def render_answer_boundary_panel(title, fields) -> None:
    rows = []
    for label, value in fields:
        rows.append(
            f"""
            <div class="boundary-row">
                <div class="boundary-label">{escape(str(label))}</div>
                <div class="boundary-value">{escape(str(value if _has_value(value) else "暂无记录"))}</div>
            </div>
            """
        )
    render_html(
        f"""
        <div class="answer-boundary-panel">
            <h4>{escape(str(title))}</h4>
            {"".join(rows)}
        </div>
        """
    )


def render_preference_comparison(
    preferred_title: str,
    preferred_answer: object,
    rejected_title: str,
    rejected_answer: object,
    preferred_meta: object | None = None,
    rejected_meta: object | None = None,
) -> None:
    """Render preferred and rejected answers with missing-value guardrails."""
    import streamlit as st

    def display_value(value: object, fallback: str = "未标注") -> str:
        if value is None:
            return fallback
        text_value = str(value).strip()
        if not text_value or text_value.lower() in {"nan", "none", "null"}:
            return fallback
        return text_value

    preferred_answer_html = escape(display_value(preferred_answer, "暂无回答内容。")).replace(chr(10), "<br>")
    rejected_answer_html = escape(display_value(rejected_answer, "暂无回答内容。")).replace(chr(10), "<br>")
    preferred_meta_text = display_value(preferred_meta, "")
    rejected_meta_text = display_value(rejected_meta, "")
    preferred_meta_html = f'<div class="comparison-meta">{escape(preferred_meta_text)}</div>' if preferred_meta_text else ""
    rejected_meta_html = f'<div class="comparison-meta">{escape(rejected_meta_text)}</div>' if rejected_meta_text else ""

    render_html(
        f"""
        <div class="comparison-grid">
            <div class="comparison-card comparison-card-preferred">
                <div class="comparison-label">偏好回答</div>
                <h4>{escape(display_value(preferred_title, "偏好回答"))}</h4>
                {preferred_meta_html}
                <div class="comparison-answer" style="white-space: pre-wrap; line-height: 1.65;">{preferred_answer_html}</div>
            </div>
            <div class="comparison-card comparison-card-rejected">
                <div class="comparison-label">对比回答</div>
                <h4>{escape(display_value(rejected_title, "对比回答"))}</h4>
                {rejected_meta_html}
                <div class="comparison-answer" style="white-space: pre-wrap; line-height: 1.65;">{rejected_answer_html}</div>
            </div>
        </div>
        """
    )

def _score_text_and_level(score) -> tuple[str, str]:
    if not _has_value(score):
        return "暂无评分", "neutral"
    value = float(score)
    if value >= 80:
        return f"{value:.0f}", "high"
    if value >= 60:
        return f"{value:.0f}", "mid"
    return f"{value:.0f}", "low"


def _normalize_level(level) -> str:
    level_text = str(level).strip().lower()
    mapping = {
        "高": "danger",
        "中": "warning",
        "低": "neutral",
        "通过": "success",
        "成功": "success",
        "warning": "warning",
        "danger": "danger",
        "error": "danger",
        "high": "danger",
        "medium": "warning",
        "low": "neutral",
        "success": "success",
        "neutral": "neutral",
        "muted": "muted",
    }
    return mapping.get(level_text, "neutral")


def _has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return True


# --------------------------------------------------------------------------- #
# Portfolio case-study components (PR-UI)
# --------------------------------------------------------------------------- #
def render_hero(eyebrow, title, subtitle, value_line, stats=None) -> None:
    """Render the portfolio hero: large title, subtitle, value line and a set
    of dynamic stat cards on the right.

    `stats` is a list of (value, label) tuples — every value should be derived
    from live data, never hardcoded. When `stats` is empty the right column is
    omitted, so the hero degrades gracefully with no data.
    """
    stat_html = "".join(
        f'<div class="fde-hero-stat">'
        f'<div class="fde-hero-stat-value">{escape(str(value))}</div>'
        f'<div class="fde-hero-stat-label">{escape(str(label))}</div>'
        f"</div>"
        for value, label in (stats or [])
    )
    aside_html = f'<div class="fde-hero-aside">{stat_html}</div>' if stat_html else ""
    eyebrow_html = f'<div class="fde-hero-eyebrow">{escape(str(eyebrow))}</div>' if eyebrow else ""
    value_html = f'<p class="fde-hero-value">{escape(str(value_line))}</p>' if value_line else ""
    render_html(
        f"""
        <div class="fde-hero">
            <div class="fde-hero-main">
                {eyebrow_html}
                <h1 class="fde-hero-title">{escape(str(title))}</h1>
                <p class="fde-hero-subtitle">{escape(str(subtitle))}</p>
                {value_html}
            </div>
            {aside_html}
        </div>
        """
    )


def render_section_block(index, title, description=None) -> None:
    """Numbered section header (01 / 02 / 03 …) for the case-study narrative."""
    desc_html = (
        f'<div class="section-block-desc">{escape(str(description))}</div>' if description else ""
    )
    render_html(
        f"""
        <div class="section-block">
            <div class="section-block-index">{escape(str(index))}</div>
            <div class="section-block-body">
                <div class="section-block-title">{escape(str(title))}</div>
                {desc_html}
            </div>
        </div>
        """
    )


def render_feature_card(items) -> None:
    """Render a responsive, auto-wrapping grid of feature cards.

    `items` is a list of (title, body) tuples.
    """
    cards = "".join(
        f'<div class="feature-card">'
        f'<div class="feature-card-title">{escape(str(title))}</div>'
        f'<div class="feature-card-body">{escape(str(body))}</div>'
        f"</div>"
        for title, body in items
    )
    render_html(f'<div class="feature-grid">{cards}</div>')


def render_case_study_card(title, summary, tags=None, metrics=None) -> None:
    """Render a single case-study card with optional tags and metric footer.

    `tags` is a list of strings; `metrics` is a list of (label, value) tuples.
    """
    tag_html = "".join(
        f'<span class="status-pill status-pill-accent">{escape(str(tag))}</span>'
        for tag in (tags or [])
    )
    tags_block = f'<div class="case-study-tags">{tag_html}</div>' if tag_html else ""
    metric_html = "".join(
        f'<div><div class="case-study-metric-value">{escape(str(value))}</div>'
        f'<div class="case-study-metric-label">{escape(str(label))}</div></div>'
        for label, value in (metrics or [])
    )
    metrics_block = f'<div class="case-study-metrics">{metric_html}</div>' if metric_html else ""
    render_html(
        f"""
        <div class="case-study-card">
            <div class="case-study-head">
                <span class="case-study-title">{escape(str(title))}</span>
                {tags_block}
            </div>
            <div class="case-study-summary">{escape(str(summary))}</div>
            {metrics_block}
        </div>
        """
    )


# Pill level → CSS modifier. Accepts the shared status vocabulary plus a few
# convenience aliases so callers can pass natural labels.
_PILL_LEVELS = {
    "success": "success", "通过": "success", "ok": "success",
    "warning": "warning", "warn": "warning", "中": "warning",
    "danger": "danger", "error": "danger", "高": "danger",
    "accent": "accent", "info": "accent",
    "neutral": "neutral",
}


def render_status_pill(text, level: str = "neutral") -> None:
    cls = _PILL_LEVELS.get(str(level).strip().lower(), "neutral")
    render_html(f'<span class="status-pill status-pill-{cls}">{escape(str(text))}</span>')


def render_cta_group(actions, note=None, key_prefix: str = "cta") -> None:
    """Render a row of call-to-action buttons that navigate to pages.

    `actions` is a list of (label, page_key) tuples. `key_prefix` keeps button
    keys unique when more than one CTA group lives on the same page.
    """
    import streamlit as st

    if not actions:
        return
    cols = st.columns(len(actions))
    for col, (label, page_key) in zip(cols, actions):
        with col:
            if st.button(label, key=f"{key_prefix}_{page_key}", use_container_width=True):
                st.session_state.current_page = page_key
                st.rerun()
    if note:
        render_html(f'<div class="cta-note">{escape(str(note))}</div>')


# --------------------------------------------------------------------------- #
# Portfolio case-study shared components (PR-UI2)
# --------------------------------------------------------------------------- #

def render_compact_hero(
    eyebrow: str,
    title: str,
    question: str | None = None,
    stats: list[tuple[str, str]] | None = None,
) -> None:
    """Compact hero for business pages: eyebrow + title + optional question + stat cards.

    `stats` is a list of (value, label) tuples — every value should be derived
    from live data, never hardcoded. When `stats` is empty the right column is
    omitted, so the hero degrades gracefully with no data.
    """
    stat_html = "".join(
        f'<div class="fde-hero-stat">'
        f'<div class="fde-hero-stat-value">{escape(str(value))}</div>'
        f'<div class="fde-hero-stat-label">{escape(str(label))}</div>'
        f"</div>"
        for value, label in (stats or [])
    )
    aside_html = f'<div class="fde-hero-aside">{stat_html}</div>' if stat_html else ""
    eyebrow_html = f'<div class="fde-hero-eyebrow">{escape(str(eyebrow))}</div>' if eyebrow else ""
    question_html = f'<p class="fde-hero-value">{escape(str(question))}</p>' if question else ""
    render_html(
        f"""
        <div class="fde-hero">
            <div class="fde-hero-main">
                {eyebrow_html}
                <h1 class="fde-hero-title">{escape(str(title))}</h1>
                {question_html}
            </div>
            {aside_html}
        </div>
        """
    )


def render_numbered_section(index: str, title: str, caption: str | None = None) -> None:
    """Numbered section header (01 / 02 / 03 …) for the case-study narrative.

    This is an alias of ``render_section_block`` with a more explicit name
    matching the portfolio vocabulary. Kept as a separate wrapper so callers
    can migrate gradually without renaming existing uses.
    """
    render_section_block(index, title, caption)


def render_feature_grid(items: list[tuple[str, str]]) -> None:
    """Render a responsive, auto-wrapping grid of feature cards.

    `items` is a list of (title, body) tuples.  Alias of ``render_feature_card``
    with a plural name that matches the portfolio vocabulary.
    """
    render_feature_card(items)


def render_evidence_panel(title: str, content_html: str) -> None:
    """Sink tables / evidence below narrative in a styled card panel.

    Use this to wrap tables, matrices, or structured data that supports the
    narrative above it. The panel visually separates "evidence" from "story".
    """
    render_html(
        f"""
        <div class="evidence-card">
            <div class="evidence-title">{escape(str(title))}</div>
            <div class="evidence-value">{content_html}</div>
        </div>
        """
    )


def render_action_cards(actions: list[tuple[str, str]], note: str | None = None, key_prefix: str = "cta") -> None:
    """Render action entry cards as a CTA button row. Alias of ``render_cta_group``."""
    render_cta_group(actions, note=note, key_prefix=key_prefix)


def render_data_table_panel(df, title: str, caption: str | None = None) -> None:
    """Wrap st.dataframe in an evidence-panel-styled card.

    Renders a compact title + optional caption above the table, then the
    interactive dataframe inside a bordered card. The dataframe itself is
    rendered via Streamlit so sorting/filtering still works.
    """
    import streamlit as st

    render_html(
        f"""
        <div class="evidence-card">
            <div class="evidence-title">{escape(str(title))}</div>
        </div>
        """
    )
    if caption:
        st.caption(caption)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_status_summary(status_items: list[tuple[str, str, str]]) -> None:
    """Render a row of status pills as a summary.

    `status_items` is a list of (label, value, level) tuples where level is one
    of the shared status vocabulary (success / warning / danger / neutral / accent).
    """
    pills = "".join(
        f'<span class="status-pill status-pill-{_PILL_LEVELS.get(str(level).strip().lower(), "neutral")}">'
        f'{escape(str(label))}：{escape(str(value))}</span>'
        for label, value, level in status_items
    )
    render_html(f'<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin:0.5rem 0 1rem 0;">{pills}</div>')


def render_portfolio_page_shell(
    page_config,
    eyebrow: str = "FinDueEval",
    hero_stats: list[tuple[str, str]] | None = None,
) -> None:
    """Unified page wrapper: compact hero + optional numbered sections start.

    Replaces the old ``render_page_shell`` for pages that want the portfolio
    case-study feel. The old ``render_page_shell`` is kept for backward
    compatibility but internally delegates to this function.
    """
    render_compact_hero(
        eyebrow=eyebrow,
        title=page_config.title,
        question=page_config.question,
        stats=hero_stats,
    )
    render_boundary_bar()


# --------------------------------------------------------------------------- #
# PR-UI6: Portfolio template new components
# --------------------------------------------------------------------------- #

def render_portfolio_landing_hero(
    title: str,
    subtitle: str,
    description: str,
    checklist_items: list[str],
    meta_line: str | None = None,
) -> None:
    """Render the portfolio-style landing hero with huge title, checklist, and mockups.

    Left side: huge title + subtitle + description + green checklist + meta line.
    Right side: webpage preview mockups (rendered separately via render_mockup_stack).
    """
    checklist_html = "".join(
        f'<div class="portfolio-checklist-item">'
        f'<span class="check-symbol">&#10003;</span> {escape(str(item))}</div>'
        for item in checklist_items
    )
    meta_html = f'<p class="portfolio-meta-line">{escape(str(meta_line))}</p>' if meta_line else ""
    render_html(
        f"""
        <div class="portfolio-hero">
            <div class="portfolio-hero-main">
                <h1 class="portfolio-hero-title">{escape(str(title))}</h1>
                <p class="portfolio-hero-subtitle">{escape(str(subtitle))}</p>
                <p class="portfolio-hero-desc">{escape(str(description))}</p>
                <div class="portfolio-checklist">{checklist_html}</div>
                {meta_html}
            </div>
            <div class="portfolio-hero-mockups">
                <!-- Mockups rendered separately via render_mockup_stack -->
            </div>
        </div>
        """
    )


def render_checklist(items: list[str]) -> None:
    """Render a standalone green checklist (no cards)."""
    html = "".join(
        f'<div class="portfolio-checklist-item">'
        f'<span class="check-symbol">&#10003;</span> {escape(str(item))}</div>'
        for item in items
    )
    render_html(f'<div class="portfolio-checklist">{html}</div>')


def render_site_mockup_preview(
    variant: str = "desktop",
    lines: int = 6,
    has_highlight: bool = True,
) -> None:
    """Render a single webpage preview mockup (desktop or mobile).

    `variant`: "desktop" or "mobile".
    `lines`: number of text lines to simulate.
    `has_highlight`: whether to include a highlighted content block.
    """
    css_class = "mockup-desktop" if variant == "desktop" else "mockup-mobile"
    line_classes = ["long", "medium", "short", "long", "medium", "short"]
    line_html = "".join(
        f'<div class="mockup-line {line_classes[i % len(line_classes)]}"></div>'
        for i in range(lines)
    )
    highlight_html = '<div class="mockup-line highlight"></div>' if has_highlight else ""
    render_html(
        f"""
        <div class="{css_class}">
            <div class="mockup-topbar">
                <div class="mockup-dot"></div>
                <div class="mockup-dot"></div>
                <div class="mockup-dot"></div>
            </div>
            <div class="mockup-nav">
                <div class="mockup-nav-item"></div>
                <div class="mockup-nav-item"></div>
                <div class="mockup-nav-item"></div>
            </div>
            {highlight_html}
            {line_html}
        </div>
        """
    )


def render_mockup_stack() -> None:
    """Render a single desktop preview mockup."""
    render_html('<div class="mockup-stack">')
    render_site_mockup_preview(variant="desktop", lines=5, has_highlight=True)
    render_html('</div>')


def render_project_meta_line(
    task_count: int,
    domain_count: int,
    scored_count: int,
    dimension_count: int,
) -> None:
    """Render a one-line meta text with dynamic project numbers."""
    text = f"{task_count} 任务 · {domain_count} 领域 · {scored_count} 已评分 · {dimension_count} 维度"
    render_html(f'<p class="portfolio-meta-line">{escape(text)}</p>')


def render_story_section(
    title: str,
    paragraphs: list[str],
    index: str | None = None,
) -> None:
    """Render a two-column story section: left big title, right paragraphs.

    `index`: optional section number like "01".
    """
    index_html = f'<span style="color:var(--portfolio-muted);font-weight:750;font-size:0.9rem;">{escape(str(index))}</span><br>' if index else ""
    body_html = "".join(
        f'<p>{escape(str(p))}</p>' for p in paragraphs
    )
    render_html(
        f"""
        <div class="story-section">
            <div>
                {index_html}
                <h2 class="story-section-title">{escape(str(title))}</h2>
            </div>
            <div class="story-section-body">{body_html}</div>
        </div>
        """
    )


def render_process_line(steps: list[str]) -> None:
    """Render a horizontal process line with arrows between nodes."""
    parts: list[str] = []
    for i, step in enumerate(steps):
        if i > 0:
            parts.append('<span class="process-arrow">→</span>')
        parts.append(f'<span class="process-node">{escape(str(step))}</span>')
    render_html(f'<div class="process-line">{"".join(parts)}</div>')


def render_pull_quote(text: str) -> None:
    """Render a styled pull quote block."""
    render_html(f'<div class="pull-quote">{escape(str(text))}</div>')


def render_tag_cloud(tags: list[str]) -> None:
    """Render a tag cloud of domain/task type labels."""
    html = "".join(f'<span class="tag-cloud-item">{escape(str(tag))}</span>' for tag in tags)
    render_html(f'<div class="tag-cloud">{html}</div>')


def render_editorial_list(items: list[tuple[str, str, int]]) -> None:
    """Render an editorial comparison list: name + judgment + small dimension bars.

    `items` is a list of (name, judgment, bar_count) tuples where bar_count
    is 0-5 representing how many dimension bars to fill.
    """
    rows: list[str] = []
    for name, judgment, bar_count in items:
        bars = "".join(
            f'<span class="editorial-bar-segment{" filled" if i < bar_count else ""}"></span>'
            for i in range(5)
        )
        rows.append(
            f'<div class="editorial-item">'
            f'<span class="editorial-item-name">{escape(str(name))}</span>'
            f'<span class="editorial-item-judgment">{escape(str(judgment))}</span>'
            f'<span class="editorial-item-bar">{bars}</span>'
            f'</div>'
        )
    render_html(f'<div class="editorial-list">{"".join(rows)}</div>')


def render_evidence_block(title: str, content_html: str) -> None:
    """Render a thin-bordered evidence block for tables/appendix content."""
    render_html(
        f"""
        <div class="evidence-block">
            <div class="evidence-block-title">{escape(str(title))}</div>
            <div>{content_html}</div>
        </div>
        """
    )


def render_conclusion_list(items: list[tuple[str, str]]) -> None:
    """Render a minimal conclusion list: text + meta per item, no cards."""
    rows = "".join(
        f'<div class="conclusion-item">'
        f'<div class="conclusion-item-text">{escape(str(text))}</div>'
        f'<div class="conclusion-item-meta">{escape(str(meta))}</div>'
        f'</div>'
        for text, meta in items
    )
    render_html(f'<div class="conclusion-list">{rows}</div>')


def render_cta_row(actions: list[tuple[str, str]], key_prefix: str = "cta") -> None:
    """Render lightweight inline CTA links that navigate to pages.

    `actions` is a list of (label, page_key) tuples.
    """
    import streamlit as st

    if not actions:
        return
    html = '<div class="cta-row">'
    for label, page_key in actions:
        # Use a Streamlit button for actual navigation, styled as a link
        html += (
            f'<span class="cta-link" onclick="">{escape(str(label))}</span>'
        )
    html += '</div>'
    render_html(html)
    # Also render actual buttons below for functionality
    cols = st.columns(len(actions))
    for col, (label, page_key) in zip(cols, actions):
        with col:
            if st.button(label, key=f"{key_prefix}_row_{page_key}", use_container_width=True):
                st.session_state.current_page = page_key
                st.rerun()


def render_key_value_list(items: list[tuple[str, str]]) -> None:
    """Render a clean key-value list without card borders.

    `items` is a list of (label, value) tuples.
    """
    pairs = "".join(
        f'<dt>{escape(str(label))}</dt><dd>{escape(str(value))}</dd>'
        for label, value in items
    )
    render_html(f'<dl class="kv-list">{pairs}</dl>')


def render_text_block(label: str, text: str) -> None:
    """Render a simple labelled text block, no card."""
    render_html(
        f'<div class="text-block">'
        f'<div class="text-block-label">{escape(str(label))}</div>'
        f'<div class="text-block-body">{escape(str(text))}</div>'
        f'</div>'
    )


def render_two_column_panel(left_html: str, right_html: str) -> None:
    """Render a two-column panel for side-by-side content."""
    render_html(
        f'<div class="two-col-panel">'
        f'<div class="col">{left_html}</div>'
        f'<div class="col">{right_html}</div>'
        f'</div>'
    )


def render_inline_status(items: list[tuple[str, str]]) -> None:
    """Render a restrained inline status line: label + value pairs.

    `items` is a list of (label, value) tuples.
    """
    parts = "".join(
        f'<span>{escape(str(label))}: <strong>{escape(str(value))}</strong></span>'
        for label, value in items
    )
    render_html(f'<div class="inline-status">{parts}</div>')


def render_clean_list(items: list[str]) -> None:
    """Render a clean bullet list without card borders."""
    rows = "".join(f'<li>{escape(str(item))}</li>' for item in items)
    render_html(f'<ul class="clean-list">{rows}</ul>')
