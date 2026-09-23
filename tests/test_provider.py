import pytest

from forgerl.provider import ProviderError, extract_source


def test_fenced_code_extraction_does_not_require_explanations():
    code,_=extract_source('```python\ndef add(a,b):\n    return a+b\n```')
    assert code.startswith('def add(')


def test_json_source_and_size_limit():
    assert extract_source('{"source":"def add(a,b): return a+b"}')[0].startswith('def add')
    with pytest.raises(ProviderError):extract_source('x'*18001)
