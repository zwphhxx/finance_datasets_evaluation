from __future__ import annotations

import re
from html import escape
from textwrap import dedent

import streamlit as st

from src.ui.responsive import MOBILE_RESPONSIVE_CSS

PROJECT_DISPLAY_NAME = "财务/法律/投行场景大模型对比评测"


STYLE_CSS = """
<style>
:root {
    --fde-bg: #f6f7f9;
    --fde-surface: #ffffff;
    --fde-surface-subtle: #fafbfc;
    --fde-line: #e1e5ec;
    --fde-line-strong: #cfd6e1;
    --fde-ink: #263241;
    --fde-text: #1f2733;
    --fde-muted: #6a7686;
    --fde-accent: #33465f;
    --fde-accent-soft: #eef2f6;
    --fde-success-bg: #edf3ef;
    --fde-success-text: #2f5d3f;
    --fde-warning-bg: #f5f0e7;
    --fde-warning-text: #6f5430;
    --fde-danger-bg: #f5ecec;
    --fde-danger-text: #7a3f3f;
    --fde-radius: 10px;
    --fde-max-width: 1120px;
}
.stApp {
    background: var(--fde-bg);
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
    max-width: var(--fde-max-width);
    margin: 0 auto;
    padding-top: 0;
    padding-bottom: 3rem;
}
[data-testid="stSidebar"] {
    display: none;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
    min-height: 56px;
    align-items: center;
    padding: 0.58rem 1.5rem 0.62rem 1.5rem;
    margin: 0.2rem 0 1.45rem 0;
    border-bottom: 1px solid var(--fde-line);
    background: transparent;
}
.top-nav-brand {
    color: var(--fde-ink);
    font-size: 1.02rem;
    font-weight: 720;
    line-height: 1.35;
    letter-spacing: 0;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
    display: flex;
    justify-content: center;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button {
    min-height: 1.9rem;
    padding: 0.18rem 0.38rem;
    border: 0;
    border: 0 !important;
    border-radius: 3px;
    background: transparent !important;
    box-shadow: none !important;
    color: var(--fde-muted);
    font-size: 0.94rem;
    font-weight: 590;
    white-space: nowrap;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button[kind="secondary"] {
    color: var(--fde-ink);
    font-weight: 720;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button:hover {
    color: var(--fde-ink);
    background: transparent !important;
}
@media (max-width: 860px) {
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        flex-wrap: wrap;
        min-height: auto;
        padding: 0.55rem 1rem 0.65rem 1rem;
    }
    .top-nav-brand {
        font-size: 0.92rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
        justify-content: flex-start;
    }
}
.page-title-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin: 0.35rem 0 1rem 0;
}
.page-title-main {
    min-width: 0;
}
.page-title-heading,
[data-testid="stMarkdownContainer"] .page-title-heading {
    color: var(--fde-ink);
    font-size: 1.45rem;
    font-weight: 760;
    line-height: 1.24;
    margin: 0;
    padding: 0;
    letter-spacing: 0;
}
.page-title-copy {
    color: var(--fde-muted);
    font-size: 0.95rem;
    line-height: 1.55;
    margin-top: 0.32rem;
}
.page-title-actions {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    flex-shrink: 0;
}
.compact-hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 1.3rem;
    align-items: end;
    margin: 0.35rem 0 1.2rem 0;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid var(--fde-line);
}
.compact-hero-eyebrow {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 700;
    margin-bottom: 0.22rem;
}
.compact-hero-title,
[data-testid="stMarkdownContainer"] .compact-hero-title {
    color: var(--fde-ink);
    font-size: 1.62rem;
    font-weight: 780;
    line-height: 1.22;
    margin: 0;
    padding: 0;
}
.compact-hero-copy {
    color: var(--fde-muted);
    font-size: 0.96rem;
    line-height: 1.58;
    margin: 0.38rem 0 0 0;
}
.compact-hero-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.7rem;
    justify-content: flex-end;
}
.compact-hero-stat {
    min-width: 5.2rem;
    border-left: 1px solid var(--fde-line);
    padding-left: 0.75rem;
}
.compact-hero-stat strong {
    display: block;
    color: var(--fde-ink);
    font-size: 1.25rem;
    line-height: 1.1;
}
.compact-hero-stat span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.78rem;
    margin-top: 0.2rem;
}
.brief-intro {
    margin: 0.35rem 0 1.45rem 0;
    padding-bottom: 0;
}
.brief-title,
[data-testid="stMarkdownContainer"] .brief-title {
    color: var(--fde-ink);
    font-size: 2.35rem;
    font-weight: 820;
    line-height: 1.12;
    letter-spacing: 0;
    margin: 0;
    max-width: 58rem;
    padding: 0;
}
.process-line {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.58rem;
    margin: 0.95rem 0 0.25rem 0;
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 700;
}
.process-line-separator {
    width: 2.2rem;
    height: 1px;
    background: var(--fde-line-strong);
    flex: 0 0 auto;
}
.process-line-text {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 680;
    line-height: 1.5;
    margin: 0.85rem 0 0.35rem 0;
}
.brief-note {
    border-left: 2px solid var(--fde-accent);
    color: var(--fde-ink);
    font-size: 1rem;
    line-height: 1.65;
    margin: 0.75rem 0 0 0;
    max-width: 50rem;
    padding-left: 0.85rem;
}
.home-section {
    margin: 2.25rem 0 0 0;
    padding: 1.55rem 0 0 0;
    border-top: 1px solid var(--fde-line-strong);
}
.home-section-first {
    border-top: 0;
    padding-top: 0;
}
.section-heading {
    display: grid;
    grid-template-columns: 4.2rem minmax(0, 1fr);
    column-gap: 1rem;
    align-items: baseline;
}
.section-heading-number {
    color: var(--fde-accent);
    font-weight: 820;
    line-height: 1;
    letter-spacing: 0;
}
.section-heading-title,
[data-testid="stMarkdownContainer"] .section-heading-title {
    color: var(--fde-ink);
    font-weight: 820;
    line-height: 1.16;
    margin: 0;
    padding: 0;
}
.section-heading-lead {
    color: var(--fde-muted);
    line-height: 1.55;
    margin-top: 0.32rem;
}
.section-heading-home {
    grid-template-columns: 4.8rem minmax(0, 1fr);
    column-gap: 1.25rem;
    margin-bottom: 0.9rem;
}
.section-heading-home .section-heading-number {
    font-size: 2.05rem;
}
.section-heading-home .section-heading-title {
    font-size: 1.62rem;
}
.section-heading-home .section-heading-lead {
    color: var(--fde-text);
    font-size: 1.03rem;
    font-weight: 680;
    margin-top: 0.48rem;
}
.section-heading-page {
    grid-template-columns: 3.4rem minmax(0, 1fr);
    column-gap: 1rem;
    margin: 1.9rem 0 0.95rem 0;
    padding-top: 1rem;
    border-top: 1px solid var(--fde-line);
}
.section-heading-page .section-heading-number {
    font-size: 1.08rem;
}
.section-heading-page .section-heading-title {
    font-size: 1.28rem;
}
.section-heading-page .section-heading-lead {
    font-size: 0.94rem;
    font-weight: 400;
}
.home-section-body {
    margin-left: 6.05rem;
}
.home-section-body p {
    color: var(--fde-text);
    font-size: 0.96rem;
    font-weight: 400;
    line-height: 1.72;
    margin: 0 0 0.72rem 0;
}
.inline-status {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.55rem 0.8rem;
    margin: 0.45rem 0 0.75rem 0;
}
.inline-status-item {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.28rem 0 0.42rem 0;
}
.inline-status-item span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.75rem;
    font-weight: 650;
    margin-bottom: 0.16rem;
}
.inline-status-item strong {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 650;
    line-height: 1.45;
}
.aux-action-bar {
    border-top: 1px solid var(--fde-line);
    color: var(--fde-muted);
    font-size: 0.82rem;
    font-weight: 680;
    line-height: 1.45;
    margin: 0.5rem 0 0.35rem 0;
    padding-top: 0.58rem;
}
.aux-action-bar-label {
    color: var(--fde-muted);
    font-size: 0.82rem;
    font-weight: 680;
    line-height: 1.45;
}
.aux-action-static-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin: 0.1rem 0 0.75rem 0;
}
.aux-action-static {
    border: 1px solid var(--fde-line);
    border-radius: 8px;
    color: var(--fde-text);
    display: inline-flex;
    font-size: 0.86rem;
    font-weight: 650;
    padding: 0.32rem 0.62rem;
}
.empty-state {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    background: var(--fde-surface-subtle);
    color: var(--fde-muted);
    padding: 1rem 1.1rem;
    line-height: 1.6;
    margin: 0.5rem 0 1rem 0;
}
.detail-panel,
.sample-detail-panel {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    background: var(--fde-surface);
    overflow: hidden;
    margin: 0.55rem 0 1rem 0;
}
.detail-panel-header,
.sample-detail-panel-header {
    padding: 0.82rem 1rem;
    border-bottom: 1px solid var(--fde-line);
}
.detail-panel-title,
.sample-detail-panel-title {
    color: var(--fde-ink);
    font-size: 1rem;
    font-weight: 720;
    line-height: 1.45;
}
.detail-panel-meta,
.sample-detail-panel-meta {
    color: var(--fde-muted);
    font-size: 0.86rem;
    line-height: 1.45;
    margin-top: 0.18rem;
}
.detail-panel-body,
.sample-detail-panel-body {
    padding: 0.95rem 1rem 1.1rem 1rem;
}
.sample-detail-toolbar-title {
    padding: 0.42rem 0;
}
.sample-detail-toolbar-title div {
    color: var(--fde-ink);
    font-size: 1.02rem;
    font-weight: 720;
    line-height: 1.42;
    overflow-wrap: anywhere;
}
.sample-detail-toolbar-title span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.86rem;
    margin-top: 0.22rem;
}
[data-testid="stHorizontalBlock"]:has(.sample-detail-toolbar-title) {
    align-items: start;
    gap: 0.55rem;
    margin-bottom: 0.45rem;
}
[data-testid="stHorizontalBlock"]:has(.sample-detail-toolbar-title) .stButton > button {
    margin-top: 0.1rem;
}
.sample-detail-section {
    margin-top: 1.05rem;
}
.sample-detail-section:first-child {
    margin-top: 0;
}
.sample-detail-section-title {
    color: var(--fde-muted);
    font-size: 0.84rem;
    font-weight: 760;
    margin-bottom: 0.48rem;
}
.document-block,
.document-section,
.markdown-detail-body,
.review-summary-panel-body {
    max-width: min(100%, 960px);
}
.document-section {
    margin-top: 1.1rem;
}
.document-section:first-child {
    margin-top: 0;
}
.document-section-title {
    color: var(--fde-ink);
    font-size: 0.96rem;
    font-weight: 760;
    line-height: 1.45;
    margin: 0 0 0.62rem 0;
}
.document-field {
    margin: 0;
}
.document-field + .document-field {
    border-top: 1px solid var(--fde-line);
    margin-top: 0.72rem;
    padding-top: 0.68rem;
}
.document-field-title {
    color: var(--fde-accent);
    font-size: 0.82rem;
    font-weight: 760;
    line-height: 1.45;
    margin: 0 0 0.28rem 0;
}
.document-text {
    color: var(--fde-text);
    font-size: 0.95rem;
    font-weight: 400;
    line-height: 1.72;
}
.document-text p {
    margin: 0 0 0.58rem 0;
}
.document-text p:last-child {
    margin-bottom: 0;
}
.document-list {
    color: var(--fde-text);
    font-size: 0.95rem;
    font-weight: 400;
    line-height: 1.68;
    margin: 0.15rem 0 0.05rem 1.08rem;
    padding: 0;
}
.document-list li {
    margin: 0.26rem 0;
    padding-left: 0.08rem;
}
.document-list-risk li::marker {
    color: var(--fde-danger-text);
}
.sample-detail-kv-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
    gap: 0.45rem 0.9rem;
}
.sample-detail-kv {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.28rem 0 0.42rem 0;
}
.sample-detail-kv span,
.sample-detail-label {
    display: block;
    color: var(--fde-muted);
    font-size: 0.76rem;
    font-weight: 700;
    margin: 0.25rem 0 0.18rem 0;
}
.sample-detail-kv strong,
.sample-detail-text,
.sample-detail-list {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 400;
    line-height: 1.62;
}
.sample-detail-text {
    margin: 0 0 0.55rem 0;
}
.sample-detail-list {
    margin: 0 0 0.65rem 1.1rem;
    padding: 0;
}
.sample-detail-list li {
    margin: 0.16rem 0;
}
.sample-detail-table,
.check-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    line-height: 1.5;
}
.sample-detail-table th,
.sample-detail-table td,
.check-table td {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.5rem 0.45rem;
    vertical-align: top;
}
.sample-detail-table th {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 720;
    text-align: left;
    background: var(--fde-surface-subtle);
}
.answer-viewer-summary {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    background: var(--fde-surface);
    padding: 0.8rem 0.95rem;
    margin: 0.55rem 0 0.8rem 0;
}
.answer-viewer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.5rem 0.8rem;
}
.answer-viewer-item {
    border-bottom: 1px solid var(--fde-line);
    padding-bottom: 0.34rem;
}
.answer-viewer-item span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.74rem;
    font-weight: 650;
}
.answer-viewer-item strong {
    color: var(--fde-ink);
    font-size: 0.92rem;
    font-weight: 650;
    line-height: 1.45;
}
.answer-viewer-muted {
    color: var(--fde-muted);
    font-size: 0.78rem;
    margin-top: 0.5rem;
    overflow-wrap: anywhere;
}
[data-testid="stVerticalBlock"]:has(
    > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"]
    .review-summary-toolbar-title
) {
    border-color: var(--fde-line) !important;
    border-radius: var(--fde-radius) !important;
    background: var(--fde-surface) !important;
    box-shadow: none !important;
    gap: 0.25rem;
}
[data-testid="stHorizontalBlock"]:has(.review-summary-toolbar-title) {
    align-items: start;
    gap: 0.65rem;
    padding-bottom: 0.62rem;
    border-bottom: 1px solid var(--fde-line);
}
.review-summary-toolbar-title div {
    color: var(--fde-ink);
    font-size: 1.01rem;
    font-weight: 720;
    line-height: 1.44;
    overflow-wrap: anywhere;
}
.review-summary-toolbar-title span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.84rem;
    line-height: 1.5;
    margin-top: 0.18rem;
    overflow-wrap: anywhere;
}
.detail-panel-toolbar-title div {
    color: var(--fde-ink);
    font-size: 1.01rem;
    font-weight: 720;
    line-height: 1.44;
    overflow-wrap: anywhere;
}
.detail-panel-toolbar-title span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.84rem;
    line-height: 1.5;
    margin-top: 0.18rem;
    overflow-wrap: anywhere;
}
[data-testid="stMarkdownContainer"]:has(.review-summary-toolbar-title),
[data-testid="stMarkdownContainer"]:has(.detail-panel-toolbar-title),
[data-testid="stMarkdownContainer"]:has(.sample-detail-toolbar-title) {
    margin-bottom: 0 !important;
}
[data-testid="stVerticalBlock"]:has(
    > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"]
    .detail-panel-toolbar-title
) {
    border-color: var(--fde-line) !important;
    border-radius: var(--fde-radius) !important;
    background: var(--fde-surface) !important;
    box-shadow: none !important;
    gap: 0.25rem;
}
[data-testid="stHorizontalBlock"]:has(.detail-panel-toolbar-title) {
    align-items: start;
    gap: 0.65rem;
    padding-bottom: 0.62rem;
    border-bottom: 1px solid var(--fde-line);
}
[data-testid="stHorizontalBlock"]:has(.detail-panel-toolbar-title) .stButton > button {
    margin-top: 0.05rem;
}
.review-summary-panel-body {
    padding-top: 0.5rem;
}
.review-summary-section {
    margin-top: 0.92rem;
}
.review-summary-section:first-child {
    margin-top: 0;
}
.review-summary-section-title {
    color: var(--fde-muted);
    font-size: 0.84rem;
    font-weight: 760;
    margin-bottom: 0.42rem;
}
.review-summary-text {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 400;
    line-height: 1.62;
    margin: 0;
    overflow-wrap: anywhere;
}
.review-summary-list {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 400;
    line-height: 1.62;
    margin: 0 0 0.1rem 1.1rem;
    padding: 0;
}
.review-summary-list li {
    margin: 0.16rem 0;
}
.markdown-detail-body {
    color: var(--fde-ink);
    font-size: 0.95rem;
    font-weight: 400;
    line-height: 1.72;
}
.markdown-detail-body p {
    margin: 0 0 0.72rem 0;
    font-weight: 400;
}
.markdown-detail-heading {
    color: var(--fde-accent);
    font-size: 0.88rem;
    font-weight: 760;
    line-height: 1.45;
    margin: 1.05rem 0 0.46rem 0;
}
.markdown-detail-heading:first-child {
    margin-top: 0;
}
.markdown-detail-list {
    margin: 0.28rem 0 0.78rem 1.12rem;
    padding: 0;
}
.markdown-detail-list li {
    margin: 0.26rem 0;
    line-height: 1.68;
}
.markdown-detail-code {
    background: var(--fde-surface-subtle);
    border: 1px solid var(--fde-line);
    border-radius: 8px;
    color: var(--fde-text);
    font-size: 0.84rem;
    line-height: 1.55;
    margin: 0.55rem 0 0.8rem 0;
    overflow: auto;
    padding: 0.68rem 0.78rem;
}
.markdown-detail-inline-code {
    background: var(--fde-surface-subtle);
    border: 1px solid var(--fde-line);
    border-radius: 4px;
    padding: 0.04rem 0.24rem;
}
.markdown-detail-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    line-height: 1.5;
    margin: 0.5rem 0 0.85rem 0;
}
.markdown-detail-table th,
.markdown-detail-table td {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.45rem 0.45rem;
    text-align: left;
    vertical-align: top;
}
.markdown-detail-table th {
    background: var(--fde-surface-subtle);
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 720;
}
.clean-list {
    margin: 0.25rem 0 0.85rem 1.1rem;
    padding: 0;
    color: var(--fde-ink);
    line-height: 1.65;
}
.clean-list li {
    margin: 0.18rem 0;
}
.inline-pill {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--fde-line);
    border-radius: 999px;
    background: var(--fde-surface-subtle);
    color: var(--fde-muted);
    padding: 0.12rem 0.5rem;
    font-size: 0.78rem;
    font-weight: 650;
}
.inline-pill-success {
    background: var(--fde-success-bg);
    color: var(--fde-success-text);
}
.inline-pill-warning {
    background: var(--fde-warning-bg);
    color: var(--fde-warning-text);
}
.inline-pill-danger {
    background: var(--fde-danger-bg);
    color: var(--fde-danger-text);
}
.stButton > button {
    border-radius: 6px !important;
    box-shadow: none !important;
    font-weight: 650 !important;
}
.stButton > button[kind="primary"] {
    background: var(--fde-accent) !important;
    border: 1px solid var(--fde-accent) !important;
    color: #ffffff !important;
}
.stButton > button[kind="secondary"] {
    background: var(--fde-surface) !important;
    border: 1px solid var(--fde-line-strong) !important;
    color: var(--fde-ink) !important;
}
.stButton > button[kind="tertiary"] {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--fde-muted) !important;
}
.stButton > button:hover {
    border-color: var(--fde-line-strong) !important;
    color: var(--fde-ink) !important;
}
[data-testid="stDataFrame"] {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    overflow: hidden;
    background: var(--fde-surface);
}
[data-testid="stDataFrame"] [role="columnheader"] {
    background: var(--fde-surface-subtle) !important;
    color: var(--fde-muted) !important;
    font-weight: 700 !important;
}
[data-testid="stDataFrame"] [role="gridcell"] {
    color: var(--fde-ink) !important;
}
div[data-testid="stAlert"] {
    border-radius: var(--fde-radius);
    border: 1px solid var(--fde-line);
    box-shadow: none;
}
div[data-testid="stDialog"] {
    color: var(--fde-text);
}
@media (max-width: 760px) {
    .page-title-row,
    .compact-hero {
        grid-template-columns: 1fr;
        display: block;
    }
    .page-title-actions,
    .compact-hero-stats {
        justify-content: flex-start;
        margin-top: 0.75rem;
    }
    .section-heading,
    .section-heading-home,
    .section-heading-page {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: start;
    }
    .brief-title {
        font-size: 1.78rem;
    }
    .process-line-separator {
        width: 1.2rem;
    }
    .section-heading-home .section-heading-number {
        font-size: 1.55rem;
    }
    .section-heading-home .section-heading-title {
        font-size: 1.34rem;
    }
    .section-heading-page .section-heading-number {
        font-size: 0.98rem;
    }
    .section-heading-page .section-heading-title {
        font-size: 1.16rem;
    }
    .home-section-body {
        margin-left: 0;
    }
}
</style>
"""

STYLE_CSS = STYLE_CSS.replace(
    "</style>",
    f"{MOBILE_RESPONSIVE_CSS}\n</style>",
)


def _clean_html(html: str) -> str:
    text = dedent(str(html or "")).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "".join(lines)


def render_html(html: str, container=None) -> None:
    target = container or st
    target.markdown(_clean_html(html), unsafe_allow_html=True)


def apply_global_styles() -> None:
    render_html(STYLE_CSS)


def render_page_heading(title: str, description: str | None = None) -> None:
    desc_html = (
        f'<div class="page-title-copy">{escape(str(description))}</div>'
        if description
        else ""
    )
    render_html(
        f"""
        <div class="page-title-row">
            <div class="page-title-main">
                <h1 class="page-title-heading">{escape(str(title))}</h1>
                {desc_html}
            </div>
        </div>
        """
    )


def render_compact_hero(
    eyebrow: str,
    title: str,
    question: str | None = None,
    stats: list[tuple[str, str]] | None = None,
) -> None:
    stat_html = "".join(
        f'<div class="compact-hero-stat"><strong>{escape(str(value))}</strong><span>{escape(str(label))}</span></div>'
        for value, label in (stats or [])
    )
    eyebrow_html = f'<div class="compact-hero-eyebrow">{escape(str(eyebrow))}</div>' if eyebrow else ""
    question_html = f'<p class="compact-hero-copy">{escape(str(question))}</p>' if question else ""
    aside_html = f'<div class="compact-hero-stats">{stat_html}</div>' if stat_html else ""
    render_html(
        f"""
        <div class="compact-hero">
            <div>
                {eyebrow_html}
                <h1 class="compact-hero-title">{escape(str(title))}</h1>
                {question_html}
            </div>
            {aside_html}
        </div>
        """
    )


def render_brief_intro(title: str, note: str) -> None:
    render_html(
        f"""
        <div class="brief-intro">
            <h1 class="brief-title">{escape(str(title))}</h1>
            <p class="brief-note">{escape(str(note))}</p>
        </div>
        """
    )


def render_home_section(
    number: str,
    title: str,
    lead: str,
    body: list[str],
    *,
    first: bool = False,
    process_steps: list[str] | None = None,
) -> None:
    body_html = "".join(f"<p>{escape(str(paragraph))}</p>" for paragraph in body if str(paragraph).strip())
    if process_steps:
        body_html += _process_line_html(process_steps)
    section_class = "home-section home-section-first" if first else "home-section"
    heading_html = _section_heading_html(number, title, lead, variant="home")
    render_html(
        f"""
        <section class="{section_class}">
            {heading_html}
            <div class="home-section-body">{body_html}</div>
        </section>
        """
    )


def render_process_line(steps: list[str]) -> None:
    if not steps:
        return
    render_html(_process_line_html(steps))


def _process_line_html(steps: list[str]) -> str:
    parts: list[str] = []
    for index, step in enumerate(steps):
        if index:
            parts.append('<span class="process-line-separator"></span>')
        parts.append(f'<span>{escape(str(step))}</span>')
    return f'<div class="process-line">{"".join(parts)}</div>'


def _section_heading_html(
    number: str,
    title: str,
    lead: str | None = None,
    *,
    variant: str = "page",
) -> str:
    normalized = str(variant or "page").strip().lower()
    if normalized not in {"home", "page"}:
        normalized = "page"
    lead_html = (
        f'<div class="section-heading-lead">{escape(str(lead))}</div>'
        if str(lead or "").strip()
        else ""
    )
    return f"""
        <div class="section-heading section-heading-{normalized}">
            <span class="section-heading-number">{escape(str(number))}</span>
            <div class="section-heading-main">
                <h2 class="section-heading-title">{escape(str(title))}</h2>
                {lead_html}
            </div>
        </div>
    """


def render_section_heading(
    number: str,
    title: str,
    lead: str | None = None,
    *,
    variant: str = "page",
) -> None:
    render_html(_section_heading_html(number, title, lead, variant=variant))


def render_numbered_section(index: str, title: str, caption: str | None = None) -> None:
    render_section_heading(index, title, caption, variant="page")


def render_empty_state(message: str) -> None:
    render_html(f'<div class="empty-state">{escape(str(message))}</div>')


def render_inline_status(items: list[tuple[str, str]]) -> None:
    parts = "".join(
        f'<div class="inline-status-item"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in items
    )
    render_html(f'<div class="inline-status">{parts}</div>')


def render_aux_action_bar(title: str, actions: list[dict[str, object]]) -> str | None:
    """Render a low-emphasis action row and return the clicked action id."""
    usable_actions = [action for action in actions or [] if action.get("label")]
    render_html(f'<div class="aux-action-bar"><span class="aux-action-bar-label">{escape(str(title))}</span></div>')
    if not usable_actions:
        return None

    if not hasattr(st, "button"):
        static_actions = "".join(
            f'<span class="aux-action-static">{escape(str(action.get("label") or ""))}</span>'
            for action in usable_actions
        )
        render_html(f'<div class="aux-action-static-row">{static_actions}</div>')
        return None

    clicked: str | None = None
    for action in usable_actions:
        label = str(action.get("label") or "")
        action_id = str(action.get("id") or action.get("key") or label)
        if st.button(
            label,
            key=str(action.get("key") or action_id),
            type=str(action.get("type") or "secondary"),
            disabled=bool(action.get("disabled", False)),
            use_container_width=bool(action.get("use_container_width", False)),
        ):
            clicked = action_id
    return clicked


def render_document_block(body_html: str, title: str | None = None, meta: str | None = None) -> None:
    """Render long-form professional materials inside the shared detail panel."""
    content = f'<div class="document-block">{body_html}</div>'
    if title or meta:
        render_detail_panel(content, title=title, meta=meta)
        return
    render_html(content)


def render_field_section(label: str, value, fallback: str = "待补充", *, tone: str | None = None) -> str:
    """Return a shared field block for long text or list-like professional materials."""
    if isinstance(value, (list, tuple, set)):
        return _document_list_section_html(label, list(value), fallback=fallback, tone=tone)
    return render_long_text_section(label, value, fallback=fallback)


def render_long_text_section(label: str, value, fallback: str = "待补充") -> str:
    return (
        '<div class="document-field">'
        f'<div class="document-field-title">{escape(str(label))}</div>'
        f'<div class="document-text">{_document_paragraphs_html(value, fallback=fallback)}</div>'
        "</div>"
    )


def render_markdown_block(markdown_text: str) -> str:
    return f'<div class="markdown-detail-body document-markdown">{markdown_detail_html(markdown_text)}</div>'


def document_section_html(title: str, content_html: str) -> str:
    return (
        '<section class="document-section sample-detail-section">'
        f'<div class="document-section-title sample-detail-section-title">{escape(str(title))}</div>'
        f"{content_html}"
        "</section>"
    )


def _document_list_section_html(label: str, items: list, fallback: str = "待补充", tone: str | None = None) -> str:
    values = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not values:
        values = [fallback]
    tone_class = " document-list-risk" if str(tone or "").strip().lower() in {"risk", "danger"} else ""
    item_html = "".join(f"<li>{_document_inline_html(item)}</li>" for item in values)
    return (
        '<div class="document-field">'
        f'<div class="document-field-title">{escape(str(label))}</div>'
        f'<ul class="document-list{tone_class}">{item_html}</ul>'
        "</div>"
    )


def _document_paragraphs_html(value, fallback: str = "待补充") -> str:
    text = str(value or "").strip()
    if not text:
        text = str(fallback)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [str(fallback)]
    return "".join(f"<p>{_document_inline_html(paragraph)}</p>" for paragraph in paragraphs)


def _document_inline_html(value) -> str:
    return escape(str(value or "").strip()).replace("\n", "<br>")


def render_kv_grid(items: list[tuple[str, object]]) -> None:
    parts = "".join(
        f'<div class="sample-detail-kv"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in items
    )
    render_html(f'<div class="sample-detail-kv-grid">{parts}</div>')


def render_detail_panel(body_html: str, title: str | None = None, meta: str | None = None) -> None:
    header_html = ""
    if title or meta:
        title_html = f'<div class="detail-panel-title">{escape(str(title))}</div>' if title else ""
        meta_html = f'<div class="detail-panel-meta">{escape(str(meta))}</div>' if meta else ""
        header_html = f'<div class="detail-panel-header">{title_html}{meta_html}</div>'
    render_html(
        f"""
        <div class="detail-panel sample-detail-panel">
            {header_html}
            <div class="detail-panel-body sample-detail-panel-body">{body_html}</div>
        </div>
        """
    )


def render_detail_panel_with_action(
    body_html: str,
    *,
    title: str | None = None,
    meta: str | None = None,
    action_label: str | None = None,
    action_key: str | None = None,
    action_type: str = "secondary",
    action_disabled: bool = False,
) -> bool:
    """Render a detail panel with one low-emphasis action in the header."""
    if not action_label:
        render_detail_panel(body_html, title=title, meta=meta)
        return False

    if not all(hasattr(st, name) for name in ("container", "columns", "button")):
        render_detail_panel(
            body_html,
            title=title,
            meta=_join_meta_lines(meta, f"[{action_label}]"),
        )
        return False

    clicked = False
    with st.container(border=True):
        title_col, action_col = st.columns([4.8, 1.18], gap="small")
        with title_col:
            render_html(_detail_panel_toolbar_html(title, meta))
        with action_col:
            clicked = st.button(
                str(action_label),
                type=action_type,
                key=action_key or f"detail_panel_action::{title or action_label}",
                disabled=action_disabled,
                use_container_width=True,
            )
        render_html(f'<div class="detail-panel-body sample-detail-panel-body">{body_html}</div>')
    return bool(clicked)


def _detail_panel_toolbar_html(title: str | None, meta: str | None) -> str:
    title_html = f"<div>{escape(str(title))}</div>" if title else ""
    meta_html = "".join(
        f"<span>{escape(line)}</span>"
        for line in str(meta or "").splitlines()
        if line.strip()
    )
    return f'<div class="detail-panel-toolbar-title">{title_html}{meta_html}</div>'


def _join_meta_lines(*values: str | None) -> str:
    return "\n".join(str(value).strip() for value in values if str(value or "").strip())


_ORDERED_ITEM_RE = re.compile(r"^\s*(?P<number>\d+)(?:\.\s+|\)\s*|）\s*)(?P<text>.+?)\s*$")
_CHINESE_SECTION_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十百千万]+、|[（(][一二三四五六七八九十百千万]+[）)])\s*(?P<text>.+?)\s*$"
)


def markdown_detail_html(markdown_text: str) -> str:
    """Render model-authored Markdown into a constrained detail-pane HTML subset."""
    lines = str(markdown_text or "").splitlines()
    parts: list[str] = []
    list_type: str | None = None
    code_lines: list[str] = []
    in_code = False
    index = 0

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            parts.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_code:
                parts.append(
                    '<pre class="markdown-detail-code"><code>'
                    + escape("\n".join(code_lines))
                    + "</code></pre>"
                )
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
                code_lines = []
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            close_list()
            index += 1
            continue

        if _is_markdown_table_start(lines, index):
            close_list()
            table_rows, next_index = _collect_markdown_table(lines, index)
            parts.append(_markdown_table_html(table_rows))
            index = next_index
            continue

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            close_list()
            parts.append(f'<div class="markdown-detail-heading">{_inline_markdown_html(heading.group(1))}</div>')
            index += 1
            continue

        bold_heading = re.match(r"^\s*\*\*(.+?)\*\*\s*$", line)
        if bold_heading and _is_concise_detail_heading(bold_heading.group(1)):
            close_list()
            parts.append(f'<div class="markdown-detail-heading">{_inline_markdown_html(bold_heading.group(1))}</div>')
            index += 1
            continue

        if _is_chinese_section_heading(line):
            close_list()
            parts.append(f'<div class="markdown-detail-heading">{_inline_markdown_html(stripped)}</div>')
            index += 1
            continue

        unordered = re.match(r"^\s*[-*]\s+(.+)$", line)
        if unordered:
            if list_type != "ul":
                close_list()
                list_type = "ul"
                parts.append('<ul class="markdown-detail-list">')
            parts.append(f"<li>{_inline_markdown_html(unordered.group(1))}</li>")
            index += 1
            continue

        ordered = _ordered_item_match(line)
        if ordered:
            number = int(ordered.group("number"))
            item_text = ordered.group("text")
            if _is_numbered_section_heading(lines, index, ordered):
                close_list()
                parts.append(f'<div class="markdown-detail-heading">{_inline_markdown_html(stripped)}</div>')
                index += 1
                continue
            if list_type != "ol":
                close_list()
                list_type = "ol"
                start_attr = f' start="{number}"' if number != 1 else ""
                parts.append(f'<ol class="markdown-detail-list"{start_attr}>')
            parts.append(f"<li>{_inline_markdown_html(item_text)}</li>")
            index += 1
            continue

        close_list()
        parts.append(f"<p>{_inline_markdown_html(stripped)}</p>")
        index += 1

    close_list()
    if in_code:
        parts.append(
            '<pre class="markdown-detail-code"><code>'
            + escape("\n".join(code_lines))
            + "</code></pre>"
        )
    return "\n".join(parts) or "<p>—</p>"


def render_markdown_detail_panel(
    title: str,
    markdown_text: str,
    meta: str | None = None,
    *,
    action_label: str | None = None,
    action_key: str | None = None,
    action_type: str = "secondary",
    action_disabled: bool = False,
) -> bool:
    body_html = render_markdown_block(markdown_text)
    if action_label:
        return render_detail_panel_with_action(
            body_html,
            title=title,
            meta=meta,
            action_label=action_label,
            action_key=action_key,
            action_type=action_type,
            action_disabled=action_disabled,
        )
    render_detail_panel(body_html, title=title, meta=meta)
    return False


def _inline_markdown_html(text: str) -> str:
    html = escape(str(text or "").strip())
    html = re.sub(r"`([^`]+)`", r'<code class="markdown-detail-inline-code">\1</code>', html)
    html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)
    return html


def _ordered_item_match(line: str) -> re.Match[str] | None:
    return _ORDERED_ITEM_RE.match(str(line or ""))


def _is_chinese_section_heading(line: str) -> bool:
    match = _CHINESE_SECTION_RE.match(str(line or ""))
    return bool(match and _is_concise_detail_heading(match.group("text")))


def _is_numbered_section_heading(lines: list[str], index: int, match: re.Match[str]) -> bool:
    """Treat short numbered lines followed by body copy as detail-pane headings."""
    text = match.group("text")
    if not _is_concise_detail_heading(text):
        return False

    next_index = _next_nonempty_index(lines, index + 1)
    if next_index is None:
        return False

    next_line = lines[next_index]
    if _ordered_item_match(next_line):
        return False
    if re.match(r"^\s*[-*]\s+", next_line):
        return False
    if re.match(r"^\s{0,3}#{1,6}\s+", next_line):
        return False
    if next_line.strip().startswith(("```", "~~~")):
        return False
    if _is_markdown_table_start(lines, next_index):
        return False
    return True


def _next_nonempty_index(lines: list[str], start: int) -> int | None:
    for cursor in range(start, len(lines)):
        if str(lines[cursor]).strip():
            return cursor
    return None


def _is_concise_detail_heading(text: str) -> bool:
    clean = re.sub(r"[*_`]+", "", str(text or "")).strip()
    if not clean:
        return False
    if len(clean) > 48:
        return False
    return not clean.endswith(("。", "！", "？", "；", ".", "!", "?", ";"))


def _is_markdown_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    divider = lines[index + 1].strip()
    if "|" not in header or "|" not in divider:
        return False
    cells = [cell.strip() for cell in divider.strip("|").split("|")]
    return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell or "") for cell in cells)


def _collect_markdown_table(lines: list[str], index: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    cursor = index
    while cursor < len(lines):
        line = lines[cursor].strip()
        if "|" not in line:
            break
        if cursor == index + 1:
            cursor += 1
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
        cursor += 1
    return rows, cursor


def _markdown_table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = rows[0]
    body_rows = rows[1:]
    header_html = "".join(f"<th>{_inline_markdown_html(cell)}</th>" for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_inline_markdown_html(cell)}</td>" for cell in row) + "</tr>"
        for row in body_rows
    )
    return (
        '<div class="markdown-detail-table-scroll">'
        '<table class="markdown-detail-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
        "</div>"
    )


def render_clean_list(items: list[str]) -> None:
    rows = "".join(f"<li>{escape(str(item))}</li>" for item in items)
    render_html(f'<ul class="clean-list">{rows}</ul>')


def render_status_pill(text: str, level: str = "neutral") -> None:
    normalized = str(level or "neutral").strip().lower()
    if normalized not in {"success", "warning", "danger", "neutral"}:
        normalized = "neutral"
    render_html(f'<span class="inline-pill inline-pill-{normalized}">{escape(str(text))}</span>')
