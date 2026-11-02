"""Parse every source and test file without importing optional dependencies."""
import ast
from pathlib import Path


def test_all_python_files_have_valid_syntax():
    root=Path(__file__).resolve().parents[1]
    paths=sorted((root/'src').rglob('*.py'))+sorted((root/'tests').rglob('*.py'))
    assert paths, 'No Python files found'
    for path in paths:
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
