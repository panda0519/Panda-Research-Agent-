"""Panda Research Agent: Interactive dashboard for exploring research runs."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Auto-load .env environment on startup
load_dotenv()

import streamlit as st

from agents.coordinator_agent import CoordinatorAgent
from api_key_manager import (
    KEY_DEFINITIONS,
    get_env_file_keys,
    is_env_in_gitignore,
    mask_api_key,
    remove_key_from_env,
    save_keys_to_env,
    scoped_env_override,
    test_key_connection,
)
from blackboard import Blackboard
from browser_inputs import resolve_run_inputs
from sources.jev_client import is_laya_available
from storage.db import DEFAULT_DB_PATH, get_run, list_runs


st.set_page_config(
    page_title="Panda Research Agent",
    page_icon="🐼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Design tokens matching live_trace/panel.html
CUSTOM_CSS = """
<style>
/* Design Tokens from live_trace/panel.html:
 * --board: #1e2b23 | --board-edge: #141d18 | --chalk: #edece2 | --chalk-dim: rgba(237,236,226,0.58)
 * --chalk-faint: rgba(237,236,226,0.32) | --chalk-line: rgba(237,236,226,0.14)
 * --running: #e7c368 | --done: #90b99a | --error: #c3695a | --pending: rgba(237,236,226,0.28)
 * --font-display: 'Space Grotesk', system-ui, sans-serif | --font-mono: 'IBM Plex Mono', ui-monospace, monospace
 */
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --board: #1e2b23;
  --board-edge: #141d18;
  --chalk: #edece2;
  --chalk-dim: rgba(237, 236, 226, 0.58);
  --chalk-faint: rgba(237, 236, 226, 0.32);
  --chalk-line: rgba(237, 236, 226, 0.14);
  --running: #e7c368;
  --done: #90b99a;
  --error: #c3695a;
  --font-display: 'Space Grotesk', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', ui-monospace, monospace;
}

.stApp {
  background:
    radial-gradient(circle at 1px 1px, rgba(237,236,226,0.05) 1px, transparent 0) 0 0 / 5px 5px,
    radial-gradient(ellipse at 50% -10%, #1e2b23 0%, #141d18 78%) !important;
  color: #edece2 !important;
  font-family: var(--font-display);
}

[data-testid="stSidebar"] {
  background-color: #141d18 !important;
  border-right: 1px solid rgba(237, 236, 226, 0.14) !important;
}

h1, h2, h3, h4, h5, h6, [data-testid="stHeading"] {
  font-family: var(--font-display) !important;
  font-weight: 600 !important;
  color: #edece2 !important;
  letter-spacing: 0.01em;
}

[data-testid="stTabs"] [role="tablist"] {
  border-bottom: 1px dashed rgba(237, 236, 226, 0.14) !important;
  gap: 6px;
  padding-bottom: 4px;
}

[data-testid="stTabs"] [role="tab"] {
  font-family: var(--font-display) !important;
  font-size: 0.88rem !important;
  color: rgba(237, 236, 226, 0.58) !important;
  background-color: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  padding: 8px 12px !important;
  border-radius: 0 !important;
}

[data-testid="stTabs"] [role="tab"]:hover {
  color: #edece2 !important;
}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: #edece2 !important;
  font-weight: 600 !important;
  border-bottom: 2px solid #e7c368 !important;
}

[data-testid="stMetric"] {
  background-color: rgba(20, 29, 24, 0.65) !important;
  border: 1px solid rgba(237, 236, 226, 0.14) !important;
  border-radius: 4px !important;
  padding: 12px 16px !important;
}

[data-testid="stMetricValue"] {
  font-family: var(--font-mono) !important;
  font-size: 1.35rem !important;
  font-weight: 500 !important;
  color: #edece2 !important;
}

[data-testid="stMetricLabel"] {
  font-family: var(--font-display) !important;
  font-size: 0.74rem !important;
  color: rgba(237, 236, 226, 0.58) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.05em !important;
}

[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-testid="stFileUploader"] {
  background-color: rgba(0, 0, 0, 0.25) !important;
  border: 1px solid rgba(237, 236, 226, 0.14) !important;
  border-radius: 3px !important;
  color: #edece2 !important;
  font-family: var(--font-mono) !important;
}

[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"]:focus-within > div {
  border-color: #e7c368 !important;
  box-shadow: 0 0 0 1px #e7c368 !important;
}

[data-baseweb="popover"], [data-baseweb="menu"] {
  background-color: #141d18 !important;
  border: 1px solid rgba(237, 236, 226, 0.14) !important;
  color: #edece2 !important;
}

[data-testid="baseButton-secondary"], .stButton > button:not([kind="primary"]) {
  background-color: rgba(30, 43, 35, 0.4) !important;
  border: 1px solid rgba(237, 236, 226, 0.14) !important;
  color: rgba(237, 236, 226, 0.88) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.82rem !important;
  border-radius: 3px !important;
  padding: 5px 14px !important;
}

[data-testid="baseButton-secondary"]:hover, .stButton > button:not([kind="primary"]):hover {
  border-color: rgba(237, 236, 226, 0.32) !important;
  color: #edece2 !important;
  background-color: rgba(30, 43, 35, 0.7) !important;
}

[data-testid="baseButton-primary"], .stButton > button[kind="primary"] {
  background-color: #e7c368 !important;
  color: #141d18 !important;
  font-weight: 600 !important;
  border: 1px solid #e7c368 !important;
  font-family: var(--font-display) !important;
  border-radius: 3px !important;
}

button:focus-visible, a:focus-visible {
  outline: 2px solid #e7c368 !important;
  outline-offset: 2px !important;
}

[data-testid="stExpander"] {
  background-color: rgba(20, 29, 24, 0.45) !important;
  border: 1px solid rgba(237, 236, 226, 0.14) !important;
  border-radius: 4px !important;
}

code, pre, [data-testid="stCode"] {
  font-family: var(--font-mono) !important;
  background-color: rgba(0, 0, 0, 0.25) !important;
  color: #edece2 !important;
}

.stCaption, [data-testid="stCaptionContainer"] {
  font-family: var(--font-mono) !important;
  color: rgba(237, 236, 226, 0.58) !important;
  font-size: 0.78rem !important;
}

hr, [data-testid="stDivider"] {
  border-bottom: 1px dashed rgba(237, 236, 226, 0.14) !important;
  border-top: none !important;
}

[data-testid="stAlert"] {
  background-color: rgba(20, 29, 24, 0.7) !important;
  border: 1px solid rgba(237, 236, 226, 0.14) !important;
  border-radius: 4px !important;
  color: #edece2 !important;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("🐼 Panda Research Agent")

# Sidebar: Run List & Database Configuration
st.sidebar.header("Research Runs")
db_path = st.sidebar.text_input("Database Path", value=DEFAULT_DB_PATH)

runs = list_runs(db_path=db_path, limit=100)

selected_run_id = None
if runs:
    run_options = {f"{r['topic']} ({r['run_id'][:8]}...) - {r['created_at'][:16]}": r["run_id"] for r in runs}
    selected_label = st.sidebar.selectbox("Select Past Run", list(run_options.keys()))
    selected_run_id = run_options[selected_label]
else:
    st.sidebar.info("No past runs found in database.")

# Load run record if selected
run_record = get_run(selected_run_id, db_path=db_path) if selected_run_id else None
bb: Blackboard | None = None
if run_record:
    bb_data = json.loads(run_record["blackboard_json"])
    bb = Blackboard.from_dict(bb_data)


def start_run(
    topic: str,
    context: str = "",
    rubric_path: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
    env_overrides: dict[str, str] | None = None,
    depth_mode: str = "standard",
) -> CoordinatorAgent:
    """Execute a multi-agent research run with scoped environment variable overrides.

    This function is the single entry point in browser.py for instantiating and executing CoordinatorAgent.
    It encapsulates CoordinatorAgent instantiation and execution inside `scoped_env_override`
    to guarantee that any in-memory session keys are dynamically injected and cleanly restored upon completion.
    """
    if env_overrides is None:
        session_keys = st.session_state.get("session_api_keys", {}) if hasattr(st, "session_state") else {}
        env_overrides = {k: v for k, v in session_keys.items() if v}

    with scoped_env_override(env_overrides):
        try:
            coordinator = CoordinatorAgent(
                topic=topic,
                project_context=context,
                db_path=db_path,
                depth_mode=depth_mode,
            )
        except TypeError:
            coordinator = CoordinatorAgent(
                topic=topic,
                project_context=context,
                db_path=db_path,
            )
        asyncio.run(coordinator.run(rubric_path=rubric_path))
        return coordinator


def render_run_metrics() -> None:
    if run_record and bb:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Status", run_record["status"].upper())
        col2.metric("Sources & Papers", len(bb.sources) + len(bb.paper_notes))
        col3.metric("Gaps Found", len(bb.gaps))
        col4.metric("Novel Features", len(bb.proposed_features))
        col5.metric("Verifications", len(bb.claim_verifications))
        st.caption(f"**Run ID:** `{bb.run_id}` | **Created:** `{run_record['created_at']}` | **Context:** {bb.project_context or 'N/A'}")
        st.divider()


(
    tab_new_run,
    tab_api_keys,
    tab_report,
    tab_sources,
    tab_gaps,
    tab_features,
    tab_stack,
    tab_verify,
    tab_rubric,
    tab_raw,
) = st.tabs([
    "🆕 New Run",
    "🔑 API Keys",
    "📄 Full Report",
    "📚 Sources & Papers",
    "🔍 Gaps & Landscape",
    "💡 Features & Evaluations",
    "🛠️ Tech Stack",
    "🛡️ 3-Layer Verification",
    "📊 Rubric Audit",
    "🧩 Raw State",
])

# Tab 1: New Run launcher
with tab_new_run:
    st.subheader("Launch New Research Run")
    st.markdown("Enter a research topic or upload a problem description file (`.txt`, `.md`) to initiate an autonomous multi-agent research run.")

    new_topic = st.text_input(
        "Research topic",
        placeholder="e.g. On-device real-time speech diarization",
        help="Main topic or question to investigate.",
    )
    new_context = st.text_area(
        "Context / constraints",
        placeholder="e.g. Low power, <200ms latency on ARM64 wearable device",
        help="Optional additional domain requirements, constraints, or background.",
    )
    new_problem_file = st.file_uploader(
        "Or upload a problem file",
        type=["txt", "md"],
        help="Upload a .txt or .md file containing problem description or technical requirements.",
    )

    problem_file_text = None
    problem_file_name = None
    if new_problem_file is not None:
        problem_file_name = new_problem_file.name
        problem_file_text = new_problem_file.getvalue().decode("utf-8", errors="replace")
        with st.expander("📄 Uploaded Problem File Preview", expanded=True):
            st.caption(f"**Filename:** `{problem_file_name}` ({len(problem_file_text)} characters)")
            preview_content = problem_file_text[:1500] + ("\n... [remaining content truncated for preview]" if len(problem_file_text) > 1500 else "")
            st.text_area("File Preview", value=preview_content, height=140, disabled=True)

    new_rubric_file = st.file_uploader(
        "Upload Rubric (Optional YAML/JSON/MD)",
        type=["yaml", "yml", "json", "md", "txt"],
        help="Optional grading rubric for self-audit scoring.",
    )

    resolved_inputs = resolve_run_inputs(
        topic=new_topic,
        context=new_context,
        problem_file_name=problem_file_name,
        problem_file_text=problem_file_text,
    )

    can_start = resolved_inputs.is_valid and bool(resolved_inputs.topic)

    if not can_start and (bool(new_topic) or new_problem_file is not None):
        st.warning(resolved_inputs.error_message or "Please provide a valid topic or non-empty problem file.")

    depth_choice = st.radio(
        "Research Depth Mode",
        options=["⚡ Standard Research (~1-2m)", "🔬 Deep Research (~5-10m, exhaustive harvesting & full scraping)"],
        index=1,
        horizontal=True,
        help="Standard runs fast targeted searches. Deep Research performs multi-angle query decomposition, scrapes full-text web pages, queries 5 academic databases, and produces comprehensive 10-section reports.",
    )
    selected_depth = "deep" if "Deep" in depth_choice else "standard"

    if st.button("🚀 Start Research", type="primary", disabled=not can_start):
        with st.spinner("Running 11-agent pipeline..."):
            rubric_content = new_rubric_file.getvalue().decode("utf-8", errors="replace") if new_rubric_file else None
            temp_rubric_path = None
            if rubric_content:
                suffix = Path(new_rubric_file.name).suffix if new_rubric_file and new_rubric_file.name else ".yaml"
                if not suffix:
                    suffix = ".yaml"
                with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as tmp:
                    tmp.write(rubric_content)
                    temp_rubric_path = tmp.name

            try:
                coordinator = start_run(
                    topic=resolved_inputs.topic,
                    context=resolved_inputs.context,
                    rubric_path=temp_rubric_path,
                    db_path=db_path,
                    depth_mode=selected_depth,
                )
                st.success(f"Run {coordinator.run_id} finished successfully!")
                st.rerun()
            finally:
                if temp_rubric_path and Path(temp_rubric_path).exists():
                    try:
                        Path(temp_rubric_path).unlink()
                    except OSError:
                        pass



# Tab 2: API Keys Configuration
with tab_api_keys:
    st.subheader("🔑 API Key & Provider Configuration")
    st.markdown(
        "Configure provider credentials for core reasoning, multi-engine search, vector memory, "
        "and 5 real-world data verification specializations. "
        "Keys are stored in memory for this session by default; you can optionally persist them to your local `.env` file."
    )

    if "session_api_keys" not in st.session_state:
        st.session_state["session_api_keys"] = {}

    session_keys = st.session_state["session_api_keys"]
    disk_keys = get_env_file_keys(".env")

    new_input_values: dict[str, str] = {}

    current_category = None

    st.markdown("### 🔴 Required Keys (Core pipeline execution breaks without these)")
    required_vars = ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY", "VOYAGE_API_KEY", "CORE_API_KEY", "WOLFRAM_APP_ID", "TYPESAFE_API_KEY"]
    optional_vars = ["UNPAYWALL_EMAIL", "GITHUB_TOKEN", "GROQ_API_KEY", "OPENALEX_API_KEY", "CROSSREF_MAILTO"]

    def render_key_block(env_var, meta):
        st.markdown(f"**{meta['name']}** (`{env_var}`)")
        st.caption(f"{meta['description']} — [Documentation / Get Key]({meta['docs_url']})")

        session_val = session_keys.get(env_var)
        env_val = os.environ.get(env_var, "")
        effective_val = session_val if (session_val is not None and session_val != "") else env_val
        is_secret = meta.get("is_secret", True)
        placeholder_text = meta.get("placeholder", "Paste API key here..." if is_secret else "Enter value...")

        col_status, col_src = st.columns([3, 2])
        with col_status:
            if effective_val:
                st.success(f"✅ Configured: `{mask_api_key(effective_val, is_secret=is_secret)}`")
            else:
                st.warning("⚠️ Not set")
        with col_src:
            if session_val:
                st.caption("*(Active in memory for this session)*")
            elif env_var in disk_keys:
                st.caption("*(Persisted in local `.env`)*")
            elif env_val:
                st.caption("*(Inherited from process environment)*")

        col_inp, col_btn = st.columns([3, 1])
        with col_inp:
            val_typed = st.text_input(
                f"Set / Replace {meta['name']}",
                type="password" if is_secret else "default",
                key=f"input_{env_var}",
                placeholder=placeholder_text,
                label_visibility="collapsed",
            )
            if val_typed.strip():
                new_input_values[env_var] = val_typed.strip()

        with col_btn:
            if st.button("⚡ Test connection", key=f"btn_test_{env_var}"):
                key_to_test = val_typed.strip() or effective_val
                if not key_to_test:
                    st.info("Please enter or configure a value first.")
                else:
                    with st.spinner(f"Testing {meta['name']}..."):
                        ok, code, msg = test_key_connection(env_var, key_to_test)
                        if ok:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"❌ {msg}")

        sub_col1, sub_col2 = st.columns([1, 1])
        with sub_col1:
            if session_val and st.button(f"Forget session key ({env_var})", key=f"btn_forget_{env_var}"):
                session_keys.pop(env_var, None)
                st.toast(f"Cleared session value for {meta['name']}.")
                st.rerun()

        with sub_col2:
            if env_var in disk_keys:
                with st.expander(f"🗑️ Remove from saved .env ({env_var})"):
                    st.caption(f"Permanently remove `{env_var}` from `.env` on disk.")
                    if st.button(f"Confirm Delete `{env_var}`", key=f"btn_del_env_{env_var}", type="secondary"):
                        remove_key_from_env(".env", env_var)
                        st.toast(f"Removed {env_var} from .env.")
                        st.rerun()

        st.divider()

    for env_var in required_vars:
        if env_var in KEY_DEFINITIONS:
            render_key_block(env_var, KEY_DEFINITIONS[env_var])

    st.markdown("### 🟢 Optional Keys (Unlocks specific capabilities & fallbacks)")
    for env_var in optional_vars:
        if env_var in KEY_DEFINITIONS:
            render_key_block(env_var, KEY_DEFINITIONS[env_var])

    st.subheader("🧠 Typed Decision Layer & Local Model Status")
    laya_installed = is_laya_available()
    typesafe_active = bool(session_keys.get("TYPESAFE_API_KEY") or os.environ.get("TYPESAFE_API_KEY"))

    col_j, col_l = st.columns(2)
    with col_j:
        st.markdown("**TypeSafe Jev (Primary Hosted API)**")
        if typesafe_active:
            st.success("✅ Configured & Active for pipeline decisions")
        else:
            st.info("ℹ️ Unset (Automatic deterministic fallback active)")

    with col_l:
        st.markdown("**Laya Open-Weight Model (Local Backup)**")
        if laya_installed:
            st.success("✅ Installed and loadable")
        else:
            st.caption("ℹ️ Not installed (Deterministic heuristic fallback active)")

    st.divider()

    st.subheader("Save Key Changes")
    save_to_disk = st.checkbox(
        "Save these keys to my local `.env` file so I don't have to re-enter them next time",
        value=False,
        key="chk_save_to_env",
    )

    if st.button("💾 Save Keys", type="primary", key="btn_save_keys"):
        if not new_input_values:
            st.info("No new key values were entered to save.")
        else:
            for k, v in new_input_values.items():
                session_keys[k] = v

            if save_to_disk:
                if not is_env_in_gitignore():
                    st.error("Security Alert: `.env` is not listed in `.gitignore`. Refusing to write to disk.")
                else:
                    try:
                        save_keys_to_env(".env", new_input_values)
                        st.success("Keys saved to session memory and persisted to local `.env`!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to write to `.env`: {exc}")
            else:
                st.success("Keys saved to memory for this browser session only!")
                st.rerun()

# Tab 2: Full Report
with tab_report:
    if not bb:
        st.info("Please select a past run from the sidebar to view its report, or launch a new run in the '🆕 New Run' tab.")
    else:
        render_run_metrics()
        if bb.report_markdown:
            st.markdown(bb.report_markdown)
        else:
            st.write("No report generated for this run.")

# Tab 3: Sources & Papers
with tab_sources:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect sources and papers.")
    else:
        render_run_metrics()
        st.subheader("Academic Papers (arXiv & Semantic Scholar)")
        if bb.paper_notes:
            for p in bb.paper_notes:
                with st.expander(f"📄 {p.title} ({p.year or 'N/A'}) - {p.venue or p.source_api}"):
                    st.markdown(f"**Authors:** {', '.join(p.authors)}")
                    st.markdown(f"**Link:** [{p.url}]({p.url})")
                    if p.is_open_access and p.full_text_url:
                        st.markdown(f"🔓 **Open Access Full Text:** [Download PDF / View Article]({p.full_text_url}) (`{p.oa_source or 'open_access'}`)")
                    if p.takeaways:
                        st.info(f"**Key Takeaway:** {p.takeaways}")
                    st.markdown(f"**Abstract:** {p.abstract}")
        else:
            st.write("No academic papers captured.")

        st.subheader("Verified Multi-Engine Web Sources")
        if bb.sources:
            for s in bb.sources:
                engines_str = ", ".join(s.engines)
                st.markdown(f"- **[{s.title}]({s.url})** | Engines: `{engines_str}` | Trust: `{s.trust_score:.2f}`")
                st.caption(s.snippet[:250] + "...")
        else:
            st.write("No web sources captured.")

# Tab 4: Gaps & Landscape
with tab_gaps:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect gaps and landscape.")
    else:
        render_run_metrics()
        st.subheader("Existing Solutions")
        if bb.existing_solutions:
            for sol in bb.existing_solutions:
                with st.expander(f"📦 {sol.name} ({sol.category})"):
                    st.write(sol.description)
                    st.write(f"**Strengths:** {', '.join(sol.strengths)}")
                    st.write(f"**Limitations:** {', '.join(sol.limitations)}")
        else:
            st.write("No existing solutions surveyed.")

        st.subheader("Identified Gaps")
        if bb.gaps:
            for g in bb.gaps:
                st.warning(f"**[{g.gap_id}] {g.title}** (Severity: `{g.severity}`, Category: `{g.category}`)\n\n{g.description}")
        else:
            st.write("No technical gaps identified.")

# Tab 5: Features & Evaluations
with tab_features:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect features and evaluations.")
    else:
        render_run_metrics()
        eval_map = {e.feature_id: e for e in bb.evaluations}
        for feat in bb.proposed_features:
            with st.expander(f"✨ [{feat.feature_id}] {feat.title}", expanded=True):
                st.write(feat.description)
                if feat.novelty_rationale:
                    st.markdown(f"**Novelty Rationale:** {feat.novelty_rationale}")
                if feat.architecture_notes:
                    st.markdown(f"**Architecture:** {feat.architecture_notes}")

                ev = eval_map.get(feat.feature_id)
                if ev:
                    ec1, ec2, ec3 = st.columns(3)
                    ec1.metric("Feasibility", f"{ev.feasibility_score}/5")
                    ec2.metric("Complexity", f"{ev.complexity_score}/5")
                    ec3.metric("Risk Level", ev.risk_level.upper())
                    st.write(f"**Assessment:** {ev.overall_assessment}")
                    if ev.risks:
                        st.write(f"**Risks:** {', '.join(ev.risks)}")
                    if ev.mitigations:
                        st.write(f"**Mitigations:** {', '.join(ev.mitigations)}")


# Tab 6: Tech Stack
with tab_stack:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect tech stack recommendations.")
    else:
        render_run_metrics()
        st.subheader("Layer-by-Layer Tech Stack Recommendations")
        for ts in bb.tech_stack:
            st.markdown(f"### 🔹 {ts.layer.replace('_', ' ').title()}: `{ts.selected_tech}`")
            if ts.repo_url:
                st.markdown(f"- **GitHub Repository:** [{ts.repo_url}]({ts.repo_url})")
            if ts.health_notes:
                st.markdown(f"- **Repository Health:** {ts.health_notes}")
            if ts.alternatives_considered:
                st.markdown(f"- **Alternatives Considered:** {', '.join(ts.alternatives_considered)}")
            if ts.rationale:
                st.markdown(f"- **Rationale:** {ts.rationale}")

# Tab 7: 3-Layer Verification
with tab_verify:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect verification results.")
    else:
        render_run_metrics()
        st.subheader("Layer 2: Atomic Claim Verifications")
        if bb.claim_verifications:
            for cv in bb.claim_verifications:
                status_color = {"CONFIRMED": "green", "CONTRADICTED": "red", "UNSUPPORTED": "orange"}.get(cv.status, "gray")
                st.markdown(f":{status_color}[**[{cv.status}]**] ({cv.source_agent}) {cv.claim_text}")
                if cv.rationale:
                    st.caption(f"Rationale: {cv.rationale}")
        else:
            st.write("No claim verifications recorded.")

        st.subheader("Layer 3: Cross-Claim Consistency")
        if bb.consistency_issues:
            for ci in bb.consistency_issues:
                st.error(ci)
        else:
            st.success("No consistency issues or contradictions detected.")

# Tab 8: Rubric Audit
with tab_rubric:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect rubric scorecard.")
    else:
        render_run_metrics()
        st.subheader("Rubric Self-Audit Scorecard")
        if bb.rubric_scores:
            for rs in bb.rubric_scores:
                st.markdown(f"### {rs.criterion} — `{rs.score:.1f}/10.0` (Weight: {rs.weight})")
                st.write(f"**Strengths:** {rs.strengths}")
                st.write(f"**Weaknesses:** {rs.weaknesses}")
                if rs.evidence_citations:
                    st.caption(f"Evidence: {', '.join(rs.evidence_citations)}")
        else:
            st.info("No rubric was provided for this run.")

# Tab 9: Raw State
with tab_raw:
    if not bb:
        st.info("Please select a past run from the sidebar to inspect raw blackboard JSON.")
    else:
        render_run_metrics()
        st.json(bb.to_dict())

