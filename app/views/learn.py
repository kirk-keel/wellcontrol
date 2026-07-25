"""Learn page -- the teaching content from ``content/``, rendered in the app.

Runs standalone as well as under navigation, which is how it is tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_APP = Path(__file__).resolve().parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from shared import CONTENT_DIR, chapter_body, chapter_files, chapter_title  # noqa: E402

st.title("Well control — the theory")
st.caption(
    "The same material as the `content/` folder, rendered here. Read in order, "
    "or jump to the well type you are working on. Kill plans link straight to "
    "the chapter that explains their method."
)

files = chapter_files()

if not files:
    st.error(
        f"No chapters found in `{CONTENT_DIR}`. The content folder should sit "
        "alongside `app/` in the project."
    )
    st.stop()

titles = {name: chapter_title(name) for name in files}

# Honour a jump from a kill plan, defaulting to the first chapter.
target = st.session_state.get("learn_chapter", files[0])
if target not in files:
    target = files[0]

with st.sidebar:
    st.header("Contents")
    choice = st.radio(
        "Chapter",
        files,
        index=files.index(target),
        format_func=lambda name: titles[name],
        label_visibility="collapsed",
    )

st.session_state["learn_chapter"] = choice
position = files.index(choice)

st.subheader(titles[choice])
st.caption(f"Chapter {position + 1} of {len(files)}  ·  `content/{choice}`")

st.markdown(chapter_body(choice))

st.divider()
previous_column, next_column = st.columns(2)

if position > 0:
    previous_column.button(
        f"← {titles[files[position - 1]]}",
        width="stretch",
        key="learn_previous",
        on_click=lambda: st.session_state.update(
            learn_chapter=files[position - 1]
        ),
    )

if position < len(files) - 1:
    next_column.button(
        f"{titles[files[position + 1]]} →",
        width="stretch",
        key="learn_next",
        on_click=lambda: st.session_state.update(
            learn_chapter=files[position + 1]
        ),
    )

st.divider()
st.caption(
    "These are engineering aids, not a substitute for certification, a company "
    "well control manual, or the judgement of a competent person on the rig."
)
