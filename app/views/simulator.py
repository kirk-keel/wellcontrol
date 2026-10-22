"""Well Control Simulator & Teacher Station launcher view for Streamlit."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from wellcontrol.sim.scenario import SCENARIOS

st.title("🎮 Well Control Simulator & Teacher Station")

st.markdown(
    """
    The simulator forward-models a rig under the student's hands in real time.
    Bottomhole pressure, casing shoe integrity, choke manifold backpressure,
    and fluid column physics respond dynamically to live inputs.
    """
)

# Backend status check
simulator_url = "http://localhost:8000"
teacher_url = "http://localhost:8000/teacher"

col1, col2 = st.columns(2)

with col1:
    st.subheader("🖥️ Student Choke Panel")
    st.markdown(
        """
        - **Real-Time Instruments**: Standpipe, Casing, SPM, Pit Gain, Hookload.
        - **Full Rig Console**: Driller console, Choke manifold, BOP stack, P&ID.
        - **Procedural Rig Audio**: Mud pump strokes, choke fluid/gas shearing, alarms.
        - **Step-by-Step Guide**: Dynamic phase diagnosis and method checklists.
        """
    )
    st.link_button("🚀 Open Student Choke Panel", simulator_url, type="primary")

with col2:
    st.subheader("🎓 Instructor Master Station")
    st.markdown(
        """
        - **Multi-Student Live Grid**: Monitor all active students in real time.
        - **Live Fault Injector**: Trigger unexpected pump failures, choke plugs, or leaks.
        - **Master Freeze & Whiteboard**: Pause student runs to review downhole mechanics.
        - **AI Assessment & Gradebook**: Automated IADC/IWCF scoring and CSV export.
        """
    )
    st.link_button("🎓 Open Teacher Console", teacher_url, type="secondary")

st.divider()

st.subheader("📋 Scenario Direct Launch Presets")
st.markdown("Launch directly into a specific well control exercise:")

scenario_cols = st.columns(3)
for idx, sc in enumerate(SCENARIOS):
    col = scenario_cols[idx % 3]
    with col:
        with st.container(border=True):
            st.markdown(f"**{sc.name}**")
            st.caption(sc.objective)
            st.link_button(
                f"Launch '{sc.key}'",
                f"{simulator_url}/?scenario={sc.key}",
                use_container_width=True,
            )

st.divider()

st.subheader("🖥️ Embedded Simulator Preview")
st.caption(
    "If the simulator backend is running locally on port 8000, it can be flown directly below. "
    "If not yet started, launch it from terminal with: `uvicorn wellcontrol.sim.api:app --reload --port 8000`"
)

with st.expander("Show Embedded Simulator in Page", expanded=False):
    components.iframe(simulator_url, height=840, scrolling=True)
