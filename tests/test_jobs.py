from pathlib import Path

from compsognathus.core.record import ScrapedRecord
from compsognathus.downloader import DownloadResult
from compsognathus.jobs import JobStore, unique_urls


def test_unique_urls_preserva_ordem():
    assert unique_urls(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_job_store_persiste_download_e_parse(tmp_path: Path):
    urls = ["https://example.com/item"]
    store = JobStore(tmp_path / "job", urls)
    html = tmp_path / "item.html"
    html.write_text("<html></html>", encoding="utf-8")
    result = DownloadResult(urls[0], html, "httpx", True, final_url=urls[0], attempts=1)
    record = ScrapedRecord(url=urls[0], site="example", fields={"titulo": "Item"})

    store.save_download(result)
    assert store.status(urls[0]) == "downloaded"
    store.save_record(record, result)

    restored = store.load_record(urls[0])
    assert restored is not None
    restored_record, restored_result = restored
    assert restored_record.fields["titulo"] == "Item"
    assert restored_result.filepath == html
    assert store.status(urls[0]) == "parsed"


def test_job_store_rejeita_lista_diferente_ao_retomar(tmp_path: Path):
    JobStore(tmp_path / "job", ["https://example.com/a"])

    try:
        JobStore(tmp_path / "job", ["https://example.com/b"], resume=True)
    except ValueError as exc:
        assert "não correspondem" in str(exc)
    else:
        raise AssertionError("job incompatível deveria ser rejeitado")
