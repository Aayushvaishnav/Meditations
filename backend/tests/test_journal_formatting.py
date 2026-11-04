from datetime import date
from io import BytesIO
from zipfile import ZipFile

from app import db, search
from app.data_export import create_export


MARKDOWN = """# Reflection

**boldword** and *italicword* and ~~strikeword~~ and ***combinedword***.

[linkword](https://example.com/path?q=1) and `inlineword`.

> quoteword

- bulletword
  - nestedword

1. orderedword

- [ ] taskword
  - [x] checkedword

```python
codeword = 1
```
"""


def test_formatting_survives_save_search_context_and_export(client, monkeypatch, tmp_path):
    monkeypatch.setattr(search, "embed_texts", lambda texts: None)
    day = "2026-11-05"
    response = client.put(f"/api/journal/{day}", json={"raw_markdown": MARKDOWN})
    assert response.status_code == 200
    assert client.get(f"/api/journal/{day}").json()["raw_markdown"] == MARKDOWN
    for word in ["boldword", "italicword", "strikeword", "combinedword", "linkword", "inlineword", "quoteword", "nestedword", "orderedword", "checkedword", "codeword"]:
        assert client.get("/api/search", params={"q": word}).json()

    async def verify_context_and_export():
        async with db.get_sessionmaker()() as session:
            assert await search.content_for(session, f"journal:{day}") == MARKDOWN
        path = tmp_path / "formatted.zip"
        await create_export(db.get_engine(), path)
        return path.read_bytes()

    exported = client.portal.call(verify_context_and_export)
    with ZipFile(BytesIO(exported)) as archive:
        assert archive.read(f"journals/{date.fromisoformat(day)}.md") == MARKDOWN.encode()
