"""Benchmark suite for comparing model providers.

Runs standardized tasks across providers and reports performance:
- Latency (time to completion)
- Success rate
- Output quality metrics (length, structure)
- Cost estimation

Usage:
    vyane benchmark                    # all available providers
    vyane benchmark --providers codex gemini
    vyane benchmark --tasks code_review reasoning
    vyane benchmark --output results.json
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Built-in benchmark tasks (short, deterministic, measurable)
BENCHMARK_TASKS: dict[str, dict] = {
    "code_review": {
        "category": "analysis",
        "description": "Review a Python function for bugs and improvements",
        "task": (
            "Review this Python function for bugs, security issues, "
            "and improvements. Be concise.\n\n"
            "```python\n"
            "def process_data(items, threshold=None):\n"
            "    results = []\n"
            "    for i in range(len(items)):\n"
            "        if items[i] > threshold:\n"
            "            results.append(items[i] * 2)\n"
            "    return results\n"
            "```"
        ),
        "expected_keywords": ["None", "TypeError", "enumerate", "list comprehension"],
    },
    "code_generation": {
        "category": "generation",
        "description": "Generate a simple utility function",
        "task": (
            "Write a Python function `retry(fn, max_attempts=3, delay=1)` "
            "that retries a callable on exception with exponential backoff. "
            "Include type hints and a docstring. Return the function only."
        ),
        "expected_keywords": ["def retry", "except", "time.sleep", "attempts"],
    },
    "reasoning": {
        "category": "reasoning",
        "description": "Solve a logic puzzle",
        "task": (
            "A farmer has a fox, a chicken, and a bag of grain. "
            "He needs to cross a river with a boat that can only "
            "carry him and one item. The fox will eat the chicken "
            "if left alone, and the chicken will eat the grain. "
            "What is the minimum number of crossings needed? "
            "Explain your reasoning step by step."
        ),
        "expected_keywords": ["7", "chicken", "fox", "grain"],
    },
    "summarization": {
        "category": "language",
        "description": "Summarize a technical paragraph",
        "task": (
            "Summarize in 2-3 sentences: "
            "The Model Context Protocol (MCP) is an open protocol that "
            "standardizes how applications provide context to LLMs. "
            "MCP provides a standardized way to connect AI models to "
            "different data sources and tools through a client-server "
            "architecture. Servers expose resources, tools, and prompts, "
            "while clients connect to servers and make these capabilities "
            "available to LLM applications."
        ),
        "expected_keywords": ["MCP", "protocol", "server", "client"],
    },
    "translation": {
        "category": "language",
        "description": "Translate English to Chinese",
        "task": (
            "Translate to Chinese (Simplified): "
            "'The quick brown fox jumps over the lazy dog.' "
            "Provide only the translation, no explanation."
        ),
        "expected_keywords": [],
    },
}


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    provider: str = ""
    task_name: str = ""
    category: str = ""
    status: str = "pending"
    duration_seconds: float = 0.0
    output_length: int = 0
    keyword_hits: int = 0
    keyword_total: int = 0
    error: str = ""

    @property
    def keyword_score(self) -> float:
        if self.keyword_total == 0:
            return 1.0
        return self.keyword_hits / self.keyword_total


@dataclass
class BenchmarkReport:
    """Complete benchmark report."""

    timestamp: str = ""
    results: list[BenchmarkResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _check_keywords(output: str, keywords: list[str]) -> tuple[int, int]:
    """Check how many expected keywords appear in output."""
    if not keywords:
        return 0, 0
    output_lower = output.lower()
    hits = sum(1 for kw in keywords if kw.lower() in output_lower)
    return hits, len(keywords)


def run_benchmark(
    providers: list[str] | None = None,
    task_names: list[str] | None = None,
    timeout: int = 120,
    workdir: str = ".",
    sandbox: str = "read-only",
) -> BenchmarkReport:
    """Run benchmark suite and return report."""
    from vyane.adapters import ADAPTERS, get_all_adapters

    all_adapters = get_all_adapters()

    # Determine providers to test
    if providers:
        test_providers = [p for p in providers if p in all_adapters]
    else:
        test_providers = []
        for name, adapter_or_cls in all_adapters.items():
            if name not in ADAPTERS:
                continue
            try:
                inst = (
                    adapter_or_cls()
                    if isinstance(adapter_or_cls, type)
                    else adapter_or_cls
                )
                if inst.check_available():
                    test_providers.append(name)
            except Exception:
                continue

    # Determine tasks
    if task_names:
        tasks = {k: v for k, v in BENCHMARK_TASKS.items() if k in task_names}
    else:
        tasks = BENCHMARK_TASKS

    report = BenchmarkReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    for task_name, task_info in tasks.items():
        for provider in test_providers:
            result = BenchmarkResult(
                provider=provider,
                task_name=task_name,
                category=task_info.get("category", ""),
            )

            try:
                adapter_or_cls = all_adapters[provider]
                adapter = (
                    adapter_or_cls()
                    if isinstance(adapter_or_cls, type)
                    else adapter_or_cls
                )

                start = time.time()
                adapter_result = asyncio.run(
                    adapter.run(
                        prompt=task_info["task"],
                        workdir=workdir,
                        sandbox=sandbox,
                        timeout=timeout,
                    )
                )
                result.duration_seconds = round(time.time() - start, 2)
                result.status = adapter_result.status
                result.error = adapter_result.error

                output = adapter_result.output or adapter_result.summary or ""
                result.output_length = len(output)

                keywords = task_info.get("expected_keywords", [])
                hits, total = _check_keywords(output, keywords)
                result.keyword_hits = hits
                result.keyword_total = total

            except Exception as e:
                result.status = "error"
                result.error = str(e)[:200]

            report.results.append(result)

    # Build summary
    report.summary = _build_summary(report.results)
    return report


def _build_summary(results: list[BenchmarkResult]) -> dict:
    """Build aggregated summary from results."""
    by_provider: dict[str, dict] = {}

    for r in results:
        if r.provider not in by_provider:
            by_provider[r.provider] = {
                "total": 0,
                "success": 0,
                "avg_duration": 0.0,
                "total_duration": 0.0,
                "avg_keyword_score": 0.0,
                "keyword_scores": [],
            }
        ps = by_provider[r.provider]
        ps["total"] += 1
        if r.status == "success":
            ps["success"] += 1
        ps["total_duration"] += r.duration_seconds
        if r.keyword_total > 0:
            ps["keyword_scores"].append(r.keyword_score)

    for ps in by_provider.values():
        if ps["total"] > 0:
            ps["avg_duration"] = round(ps["total_duration"] / ps["total"], 2)
            ps["success_rate"] = round(ps["success"] / ps["total"] * 100, 1)
        if ps["keyword_scores"]:
            ps["avg_keyword_score"] = round(
                sum(ps["keyword_scores"]) / len(ps["keyword_scores"]), 2
            )
        del ps["total_duration"]
        del ps["keyword_scores"]

    return {"by_provider": by_provider, "total_runs": len(results)}


def format_report(report: BenchmarkReport) -> str:
    """Format benchmark report as human-readable text."""
    lines = [
        "Vyane Benchmark Report",
        f"  {report.timestamp}",
        "=" * 60,
        "",
    ]

    # Per-task results
    current_task = ""
    for r in report.results:
        if r.task_name != current_task:
            current_task = r.task_name
            lines.append(f"[{r.category}] {current_task}")
            lines.append("-" * 40)

        icon = "\u2713" if r.status == "success" else "\u2717"
        kw = ""
        if r.keyword_total > 0:
            kw = f" kw:{r.keyword_hits}/{r.keyword_total}"
        line = (
            f"  {icon} {r.provider:10s} "
            f"{r.duration_seconds:6.1f}s "
            f"{r.output_length:5d}ch{kw}"
        )
        if r.error:
            line += f"  [{r.error[:40]}]"
        lines.append(line)

    # Summary
    lines.extend(["", "Summary", "=" * 60])
    for prov, ps in report.summary.get("by_provider", {}).items():
        lines.append(
            f"  {prov:10s}  "
            f"{ps.get('success_rate', 0):5.1f}% ok  "
            f"avg {ps.get('avg_duration', 0):.1f}s  "
            f"kw_score {ps.get('avg_keyword_score', 0):.0%}"
        )

    return "\n".join(lines)


def save_report(report: BenchmarkReport, path: str) -> None:
    """Save benchmark report as JSON."""
    data = {
        "timestamp": report.timestamp,
        "results": [asdict(r) for r in report.results],
        "summary": report.summary,
    }
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
