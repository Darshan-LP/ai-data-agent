from __future__ import annotations

import os
from urllib.parse import urljoin

import requests
import streamlit as st


API_BASE_URL = os.getenv("AI_DATA_AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 180


st.set_page_config(
    page_title="AI Data Agent",
    page_icon="📊",
    layout="wide",
)


def api_url(path: str) -> str:
    return f"{API_BASE_URL}/{path.lstrip('/')}"


def api_get(path: str, **kwargs):
    try:
        response = requests.get(
            api_url(path),
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


def api_post(path: str, payload: dict):
    try:
        response = requests.post(
            api_url(path),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.HTTPError as exc:
        response = exc.response
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        return None, f"API returned HTTP {response.status_code}: {detail}"
    except requests.RequestException as exc:
        return None, str(exc)


def artifact_url(path: str) -> str:
    return urljoin(f"{API_BASE_URL}/", path.lstrip("/"))


def render_artifacts(artifacts: list[dict]) -> None:
    if not artifacts:
        st.info("No chart or Excel files were generated for this run.")
        return

    st.subheader("Generated files")

    for artifact in artifacts:
        name = artifact.get("name", "Report")
        path = artifact.get("url", "")
        kind = artifact.get("kind", "")

        if not path:
            continue

        full_url = artifact_url(path)

        if kind == "image/png" or path.lower().endswith(".png"):
            st.markdown(f"**{name}**")
            st.image(full_url, use_container_width=True)

        elif (
            "spreadsheetml" in kind
            or path.lower().endswith(".xlsx")
        ):
            try:
                file_response = requests.get(
                    full_url,
                    timeout=REQUEST_TIMEOUT,
                )
                file_response.raise_for_status()

                st.download_button(
                    label=f"Download {name}",
                    data=file_response.content,
                    file_name=path.rsplit("/", 1)[-1],
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    key=f"download_{path}",
                )
            except requests.RequestException as exc:
                st.error(f"Could not load Excel file: {exc}")

        elif kind == "text/html" or path.lower().endswith(".html"):
            st.markdown(f"**{name}**")
            st.link_button(
                "Open interactive chart",
                full_url,
            )

        else:
            st.markdown(f"[{name}]({full_url})")


def ask_page() -> None:
    st.title("📊 AI Data Agent")
    st.write(
        "Ask questions about your business data. "
        "The agent can query PostgreSQL, generate charts, and export Excel reports."
    )

    health, health_error = api_get("health")

    if health_error:
        st.error(
            "Cannot connect to the FastAPI backend. "
            "Start the API server in another terminal, then refresh this page."
        )
        with st.expander("Connection details"):
            st.code(health_error)
        return

    if health.get("status") != "ok":
        st.warning("The API is running, but one or more database connections are unhealthy.")
    else:
        st.caption("API and PostgreSQL connections are healthy.")

    with st.form("ask_form"):
        question = st.text_area(
            "Your business question",
            placeholder=(
                "Example: Show the top 5 products by revenue and create a chart."
            ),
            height=110,
            max_chars=2000,
        )

        submitted = st.form_submit_button(
            "Run analysis",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not question.strip():
            st.warning("Please enter a question.")
            return

        with st.spinner("The agent is analyzing your question..."):
            result, error = api_post(
                "agent/run",
                {"question": question.strip()},
            )

        if error:
            st.error("The agent request did not complete successfully.")
            with st.expander("Error details"):
                st.code(error)
            st.info(
                "The failed run may still appear in Run history if the backend "
                "was able to save it."
            )
            return

        st.session_state["last_agent_result"] = result
        st.session_state["last_agent_question"] = question.strip()

    result = st.session_state.get("last_agent_result")

    if not result:
        st.info(
            "Enter a question above to begin. For example, ask for customer "
            "counts by segment or revenue by product."
        )
        return

    st.divider()
    st.subheader("Answer")
    st.write(result.get("answer", "No answer was returned."))

    if result.get("error"):
        st.warning(result["error"])

    render_artifacts(result.get("artifacts", []))

    st.subheader("Agent trace")
    st.caption(
        "The trace is stored in PostgreSQL. The current API response does not "
        "return the trace directly, so use Run history to inspect saved run details."
    )


def history_page() -> None:
    st.title("🕘 Run history")
    st.write("Review previous questions and the status of each agent run.")

    limit = st.selectbox(
        "Number of recent runs",
        options=[10, 20, 50, 100],
        index=1,
    )

    if st.button("Refresh history"):
        st.rerun()

    payload, error = api_get("runs", params={"limit": limit})

    if error:
        st.error("Could not load run history.")
        st.code(error)
        return

    runs = payload.get("runs", [])

    if not runs:
        st.info("No runs have been recorded yet.")
        return

    for run in runs:
        status = run.get("status", "unknown")
        question = run.get("question", "Unknown question")
        run_id = run.get("id", "—")

        with st.expander(f"Run #{run_id} · {status.upper()} · {question}"):
            col1, col2, col3 = st.columns(3)

            col1.metric("Latency", f"{run.get('latency_ms') or 0} ms")

            input_tokens = run.get("input_tokens")
            output_tokens = run.get("output_tokens")

            col2.metric(
                "Input tokens",
                input_tokens if input_tokens is not None else "Not recorded",
            )
            col3.metric(
                "Output tokens",
                output_tokens if output_tokens is not None else "Not recorded",
            )

            cost = run.get("cost_usd")
            st.caption(
                f"Created: {run.get('created_at', 'Unknown')} · "
                f"Cost: ${cost:.6f}" if cost is not None
                else f"Created: {run.get('created_at', 'Unknown')} · Cost: Not recorded"
            )

            st.markdown("**Question**")
            st.write(question)

            st.markdown("**Final answer**")
            st.write(run.get("final_answer") or "No answer recorded.")

    st.caption(
        "Token counts and cost will show as not recorded until actual model usage "
        "is captured. Detailed trace and SQL are stored in PostgreSQL; the history "
        "API will be extended to display them in a later step."
    )


with st.sidebar:
    st.title("Navigation")
    page = st.radio(
        "Choose a page",
        ["Ask", "Run history"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(f"Backend: {API_BASE_URL}")


if page == "Ask":
    ask_page()
else:
    history_page()
