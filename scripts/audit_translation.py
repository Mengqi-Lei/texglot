"""Read-only checks for a completed job; outputs local JSON for manual review.

Run from the checkout with python -m scripts.audit_translation JOB_ID ...
No model calls, job mutations, or PDF rewrites are performed.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

from app.compiler import (
    break_long_code_identifiers,
    fit_tables,
    inject_preamble,
    prepare_chinese,
)
from app.config import DATA
from app.jobs import JobManager
from app.latex import (
    MARKER,
    apply_translations,
    collect_literal_macros,
    collect_math_aliases,
    collect_numeric_registers,
    collect_prose_arguments,
    collect_text_macros,
    collect_title_macros,
    segments,
)
from app.llm import PROMPT_VERSION, validate_translation_language
from app.paper_context import extract_paper_context


def audit(job_id):
    folder = (DATA / "jobs" / job_id).resolve()
    if folder.parent != (DATA / "jobs").resolve():
        raise ValueError("Invalid job ID")
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    config = job["config"]
    root = folder / "prepared-source"
    paths = job.get("translation_files", job.get("source_files"))
    if paths is None:
        paths = JobManager.reachable_files(root, job["main"])
    dependencies = job.get("source_dependencies", paths)
    for rel in [*paths, *dependencies]:
        candidate = (root / rel).resolve()
        if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
            raise ValueError("Invalid recorded source dependency")
    macro_source = "\n".join(
        (root / rel).read_text(encoding="utf-8") for rel in dependencies
    )
    macro_options = {
        "text_macros": collect_text_macros(macro_source),
        "math_aliases": collect_math_aliases(macro_source),
        "literal_macros": collect_literal_macros(macro_source),
        "numeric_registers": collect_numeric_registers(macro_source),
        "prose_arguments": collect_prose_arguments(macro_source),
        "title_macros": collect_title_macros(macro_source),
    }
    file_items = {
        rel: segments((root / rel).read_text(encoding="utf-8"), **macro_options)
        for rel in paths
    }
    items = {item.key: item for entries in file_items.values() for item in entries}
    guidance = config.get("context_guidance", True)
    context = (
        extract_paper_context(root, job["main"], source_files=paths) if guidance else ""
    )
    fingerprint = {
        "version": PROMPT_VERSION,
        "base": config["base_url"],
        "model": config["model"],
        "language": config["target_language"],
        "glossary": config["glossary"],
        "paper_context": context,
        "context_guidance": guidance,
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode()
    ).hexdigest()
    cache_path = folder / f"cache-{digest[:16]}.json"
    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else {}
    )
    failures, samples, restored_items = [], [], {}
    for key, item in items.items():
        try:
            output = cache[key]
            validate_translation_language(item, output, config["target_language"])
            restored = item.restore(output)
            restored_items[key] = restored
            samples.append(
                {
                    "key": key,
                    "role": item.role,
                    "source": item.source,
                    "translation": restored,
                }
            )
        except (KeyError, ValueError) as exc:
            failures.append({"key": key, "reason": str(exc), "source": item.source})
    # A table adjustment may split a validated span by inserting an adjustbox.
    # Check complete files against the declared writeback pipeline instead of
    # incorrectly requiring every restored span to remain one substring.
    expected_files, table_count = {}, 0
    for rel in paths:
        expected = apply_translations(
            (root / rel).read_text(encoding="utf-8"), file_items[rel], restored_items
        )
        expected = break_long_code_identifiers(
            expected, math_aliases=macro_options["math_aliases"]
        )
        expected, count = fit_tables(expected)
        table_count += count
        if rel == job["main"]:
            expected = prepare_chinese(expected, config["target_language"], job["engine"])
        expected_files[rel] = expected
    if table_count:
        expected_files[job["main"]] = inject_preamble(
            expected_files[job["main"]], r"\usepackage{adjustbox}" + "\n"
        )
    mismatches = [
        rel
        for rel, expected in expected_files.items()
        if expected != (folder / "translated" / rel).read_text(encoding="utf-8")
    ]
    pdfs = {}
    for side in ("original", "translated"):
        path = folder / f"{side}.pdf"
        if not path.is_file():
            continue
        reader = PdfReader(path)
        page_text, extraction_errors = [], []
        for number, page in enumerate(reader.pages, 1):
            try:
                page_text.append(page.extract_text())
            except Exception as exc:
                # Text extraction is separate from rendering; preserve its
                # failure explicitly for visual review instead of losing the
                # whole paper's structural audit on a complex figure.
                page_text.append("")
                extraction_errors.append({"page": number, "error": str(exc)[:300]})
        text = "\n".join(page_text)
        pdfs[side] = {
            "pages": len(reader.pages),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "unexpanded_markers": len(MARKER.findall(text)),
            "text_extraction_errors": extraction_errors,
            "page_text_chars": [len(t.strip()) for t in page_text],
            "page_cjk_chars": [len(re.findall(r"[\u3400-\u9fff]", t)) for t in page_text],
        }
    changed_assets = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() == ".tex":
            continue
        target = folder / "translated" / path.relative_to(root)
        if (
            not target.is_file()
            or hashlib.sha256(path.read_bytes()).digest()
            != hashlib.sha256(target.read_bytes()).digest()
        ):
            changed_assets.append(str(path.relative_to(root)))
    return {
        "id": job_id,
        "name": job["name"],
        "arxiv_id": job.get("arxiv_id"),
        "status": job["status"],
        "model": config["model"],
        "context_guidance": guidance,
        "abstract_chars": len(context),
        "segments": len(items),
        "source_files": job.get("source_files", paths),
        "translation_files": paths,
        "opaque_source_files": job.get("opaque_source_files", []),
        "validated": len(samples),
        "writeback_matches": not mismatches,
        "writeback_mismatches": mismatches,
        "failures": failures,
        "pdfs": pdfs,
        "warnings": job["warnings"],
        "changed_non_tex_assets": changed_assets,
        "tokens": job["tokens"],
        "samples": samples,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    report = [audit(job_id) for job_id in args.jobs]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for item in report:
        print(
            f"{item['id']} {item['status']} {item['validated']}/{item['segments']} {item['name']}"
        )
