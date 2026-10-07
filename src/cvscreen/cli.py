"""Command line interface: `python -m cvscreen ...`"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

from . import __version__, rules
from .claude import ClaudeExtractor, ExtractionError
from .evaluate import evaluate, format_result
from .screen import rank, screen

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.normpath(os.path.join(HERE, "..", "..", "data", "sample"))


def _extractor(backend: str, fallback: Optional[str], model: Optional[str]) -> Callable[[str], Dict[str, Any]]:
    if backend == "rules":
        return rules.extract
    claude = ClaudeExtractor(model=model)

    def run(text: str) -> Dict[str, Any]:
        try:
            return claude.extract(text)
        except ExtractionError as exc:
            if fallback == "rules":
                sys.stderr.write("claude backend failed (%s) - using the rules backend\n" % exc)
                return rules.extract(text)
            raise
    return run


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="cvscreen", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def backend_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--backend", choices=("rules", "claude"), default="rules")
        p.add_argument("--fallback", choices=("rules",), help="with --backend claude: use the rules on failure")
        p.add_argument("--model", help="model for the claude backend (default: claude-opus-5-5 or $CVSCREEN_MODEL)")

    ext = sub.add_parser("extract", help="extract a profile from one document")
    ext.add_argument("file")
    backend_options(ext)

    ev = sub.add_parser("eval", help="score a backend against the labelled documents")
    ev.add_argument("--docs", default=os.path.join(SAMPLE, "documents"))
    ev.add_argument("--gold", default=os.path.join(SAMPLE, "gold.json"))
    ev.add_argument("--min-score", type=float, help="exit with status 1 below this overall score (0-1)")
    backend_options(ev)

    sc = sub.add_parser("screen", help="rank the documents of a directory against a job profile")
    sc.add_argument("directory")
    sc.add_argument("--job", default=os.path.join(SAMPLE, "job_profile.json"))
    backend_options(sc)

    rq = sub.add_parser("request", help="print the exact request the claude backend would send (no network)")
    rq.add_argument("file")
    rq.add_argument("--model")

    args = parser.parse_args(argv)

    if args.command == "request":
        print(json.dumps(ClaudeExtractor(model=args.model).build_request(_read(args.file)), indent=2, ensure_ascii=False))
        return 0

    extract = _extractor(args.backend, getattr(args, "fallback", None), getattr(args, "model", None))

    if args.command == "extract":
        print(json.dumps(extract(_read(args.file)), indent=2, ensure_ascii=False))
        return 0

    if args.command == "eval":
        result = evaluate(extract, args.docs, args.gold)
        sys.stdout.write(format_result(result, "backend: " + args.backend))
        return 1 if args.min_score is not None and result.overall < args.min_score else 0

    if args.command == "screen":
        job = json.loads(_read(args.job))
        results = {}
        for name in sorted(os.listdir(args.directory)):
            if name.endswith(".txt"):
                results[name] = screen(extract(_read(os.path.join(args.directory, name))), job)
        print("Job: %s\n" % job.get("title", "(untitled)"))
        for name in rank(results):
            outcome = results[name]
            print("%-34s %-14s nice-to-have %d/%d" % (name, outcome["verdict"], outcome["nice_met"],
                                                      len(outcome["nice_to_have"])))
            for status, reason in outcome["must_have"]:
                if status != "met":
                    print("    %-8s %s" % (status, reason))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
