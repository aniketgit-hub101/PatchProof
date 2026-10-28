"""Streamlit interface for the trusted-fixture PatchProof MVP."""

import os

import streamlit as st
from dotenv import load_dotenv

from patchproof.agent import repair_case
from patchproof.cases import get_case, list_cases


load_dotenv()
st.set_page_config(page_title="PatchProof", page_icon="🧪", layout="wide")
st.title("PatchProof")
st.caption("A proposed patch is only a hypothesis. Real test execution is the evidence.")

if not os.environ.get("NEBIUS_API_KEY", "").strip():
    st.warning(
        "Nebius credentials are not configured. Set `NEBIUS_API_KEY` in your environment or local `.env` file "
        "to enable real inference. No mock model responses are used."
    )

cases = list_cases()
selected_id = st.selectbox("Choose a bundled bug case", [case.id for case in cases], format_func=lambda case_id: next(c.title for c in cases if c.id == case_id))
case = get_case(selected_id)
left, right = st.columns([0.9, 1.1], gap="large")

with left:
    st.subheader(case.title)
    st.write(case.description)
    source_path = case.root / case.allowed_source_files[0]
    st.code(source_path.read_text(encoding="utf-8"), language="python")
    max_attempts = st.slider("Maximum model attempts", min_value=1, max_value=3, value=3)
    run_clicked = st.button("Run repair and verify", type="primary", use_container_width=True)

if run_clicked:
    with st.spinner("Running real baseline tests and, when configured, Nebius inference..."):
        try:
            st.session_state["repair_result"] = repair_case(selected_id, max_attempts=max_attempts)
        except Exception as exc:
            st.session_state.pop("repair_result", None)
            st.error(f"Workflow stopped safely ({type(exc).__name__}): {exc}")

result = st.session_state.get("repair_result")
with right:
    st.subheader("Evidence")
    if result is None or result.case_id != selected_id:
        st.info("Run the workflow to capture an actual baseline, model attempt, diff, and test result.")
    else:
        if result.verdict == "verified":
            st.success("VERIFIED — the final fixed tests passed and protected tests remained unchanged.")
        elif result.verdict == "failed":
            st.error("FAILED — the repair did not pass the required checks.")
        else:
            st.warning("UNABLE_TO_VERIFY — the workflow could not establish a trustworthy result.")
        st.caption(f"Total workflow time: {result.elapsed_sec:.2f}s · Attempts: {len(result.attempts)}")
        st.markdown("**Baseline test execution**")
        st.code(result.baseline_output, language="text")
        for attempt in result.attempts:
            title = f"Attempt {attempt.attempt_number}: {'passed' if attempt.passed else 'not verified'}"
            if attempt.error:
                title += f" — {attempt.error}"
            with st.expander(title, expanded=True):
                st.markdown("**Patch diff**")
                st.code(attempt.patch_diff or "No patch was produced.", language="diff")
                st.markdown("**Actual test output**")
                st.code(attempt.test_output or "Tests were not run for this attempt.", language="text")
        if result.final_diff and not result.attempts:
            st.markdown("**Proposed diff**")
            st.code(result.final_diff, language="diff")
        st.markdown("**Final status details**")
        st.write(f"Protected test integrity verified: **{result.tests_integrity_verified}**")
        st.code(result.final_test_output, language="text")
