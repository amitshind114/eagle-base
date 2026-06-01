"""Eagle-Base Streamlit Dashboard.

Main UI entry point. Run with:
    streamlit run ui/app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Eagle-Base",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded",
)


def sidebar():
    with st.sidebar:
        st.image("https://img.shields.io/badge/Eagle--Base-v0.1.0-blue", width=150)
        st.title("🦅 Eagle-Base")
        st.caption("Algo Research & Trading System")
        st.divider()
        return st.radio(
            "Navigate",
            options=[
                "🏠 Home",
                "📊 Data",
                "🔍 Instruments",
                "⚙️ Backtesting",
                "🧩 Strategies",
                "📈 Reporting",
                "🛡️ Risk",
                "📋 Paper Trading",
                "🤖 AI",
                "📐 Derivatives",
                "⚡ Live",
            ],
        )


def home_page():
    st.title("🦅 Eagle-Base")
    st.subheader("Algorithmic Research & Trading System")
    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Phase", "1 of 4", "Architecture Done")
    with col2:
        st.metric("Modules", "10", "Scaffolded")
    with col3:
        st.metric("Status", "Building", "Phase 3 Next")

    st.divider()
    st.subheader("Build Priority")
    priorities = [
        ("1", "Data", "🔄 Next"),
        ("2", "Instrument Resolution", "⏳ Pending"),
        ("3", "Backtesting", "⏳ Pending"),
        ("4", "Strategy Plugins", "⏳ Pending"),
        ("5", "Reporting", "⏳ Pending"),
        ("6", "Risk", "⏳ Pending"),
        ("7", "Paper Execution", "⏳ Pending"),
        ("8", "AI", "⏳ Pending"),
        ("9", "Derivatives", "⏳ Pending"),
        ("10", "Live Execution", "🔒 Last"),
    ]
    for p, name, status in priorities:
        st.write(f"`P{p}` **{name}** — {status}")


def placeholder_page(name: str):
    st.title(name)
    st.info(f"🔧 This module is scaffolded and will be built in Phase 4.")
    st.code("TODO: Implement in Phase 4", language="python")


def main():
    page = sidebar()

    if page == "🏠 Home":
        home_page()
    elif page == "📊 Data":
        placeholder_page("Data Module — Priority 1")
    elif page == "🔍 Instruments":
        placeholder_page("Instrument Resolution — Priority 2")
    elif page == "⚙️ Backtesting":
        placeholder_page("Backtesting Engine — Priority 3")
    elif page == "🧩 Strategies":
        placeholder_page("Strategy Plugins — Priority 4")
    elif page == "📈 Reporting":
        placeholder_page("Reporting — Priority 5")
    elif page == "🛡️ Risk":
        placeholder_page("Risk Manager — Priority 6")
    elif page == "📋 Paper Trading":
        placeholder_page("Paper Trading — Priority 7")
    elif page == "🤖 AI":
        placeholder_page("AI Analyzer — Priority 8")
    elif page == "📐 Derivatives":
        placeholder_page("Derivatives — Priority 9")
    elif page == "⚡ Live":
        st.title("⚡ Live Execution — Priority 10")
        st.error("⚠️ LIVE TRADING IS DISABLED. Enable only after paper trading is fully validated.")


if __name__ == "__main__":
    main()
