"""Run the README's Python blocks in order, so the documented code stays valid."""

import re
from pathlib import Path

import plotly.graph_objects as go

README = Path(__file__).parents[1] / "README.md"


def test_readme_python_blocks_run(tmp_path, monkeypatch):
    blocks = re.findall(
        pattern=r"```python\n(.*?)```",
        string=README.read_text(),
        flags=re.DOTALL,
    )
    assert len(blocks) >= 8
    # Blocks write under output/ and show figures, so isolate both.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        target=go.Figure,
        name="show",
        value=lambda self, *args, **kwargs: None,
    )
    namespace: dict = {}
    for index, block in enumerate(blocks):
        try:
            exec(
                compile(
                    source=block,
                    filename=f"README block {index + 1}",
                    mode="exec",
                ),
                namespace,
            )
        except Exception as error:
            raise AssertionError(f"README block {index + 1} failed: {error}") from error
