"""`jevmem` command-line interface."""

from __future__ import annotations

import asyncio
import tempfile

import typer
from rich.console import Console
from rich.table import Table

from jevmem.config import Settings, get_settings
from jevmem.providers.errors import ProviderError
from jevmem.providers.factory import ConfigurationError, build_jev_client, build_qwen_provider
from jevmem.providers.jev import NoulAnswer, NoulQuestion

app = typer.Typer(
    help="JevMem: decision-native long-term memory for AI agents.", no_args_is_help=True
)
console = Console()


@app.callback()
def _root() -> None:
    """JevMem CLI."""


async def _check_jev(settings: Settings) -> tuple[bool, str]:
    try:
        client = build_jev_client(settings)
    except ConfigurationError as exc:
        return False, str(exc)
    async with client:
        try:
            result = await client.evaluate(
                "I was charged twice for my subscription.",
                {"refund": NoulQuestion(instructions="Is the customer asking for money back?")},
            )
        except ProviderError as exc:
            return False, str(exc)
    answer = result.response.answers["refund"]
    p = answer.noul if isinstance(answer, NoulAnswer) else float("nan")
    cost = result.response.usage.cost
    return True, (
        f"model={result.response.model} latency={result.latency_ms:.0f}ms "
        f"noul={p:.2f} tokens={result.response.usage.input_tokens}"
        + (f" cost=${cost:.6f}" if cost is not None else "")
    )


async def _check_qwen(settings: Settings) -> tuple[bool, str]:
    try:
        provider = build_qwen_provider(settings)
    except ConfigurationError as exc:
        return False, str(exc)
    async with provider:
        try:
            result = await provider.complete(
                [{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=16
            )
        except ProviderError as exc:
            return False, str(exc)
    ok = "OK" in result.text
    return ok, (
        f"model={result.model} latency={result.latency_ms:.0f}ms reply={result.text[:20]!r} "
        f"prompt_tokens={result.prompt_tokens} reasoning_tokens={result.reasoning_tokens}"
    )


def _check_data_dir(settings: Settings) -> tuple[bool, str]:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.data_dir, delete=True):
            pass
    except OSError as exc:
        return False, f"{settings.data_dir}: {exc.strerror}"
    return True, f"{settings.data_dir.resolve()} writable"


@app.command()
def doctor() -> None:
    """Check configuration and connectivity to Jev and Qwen. Never prints secrets."""
    settings = get_settings()
    jev_ok, jev_detail = asyncio.run(_check_jev(settings))
    qwen_ok, qwen_detail = asyncio.run(_check_qwen(settings))
    data_ok, data_detail = _check_data_dir(settings)
    rows = [
        ("data dir", data_ok, data_detail),
        (
            "jev key",
            settings.jev_api_key is not None,
            "present" if settings.jev_api_key else "missing",
        ),
        ("jev endpoint", jev_ok, f"{settings.jev_base_url} → {jev_detail}"),
        ("qwen endpoint", qwen_ok, qwen_detail),
    ]
    table = Table(title="jevmem doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    for name, ok, detail in rows:
        table.add_row(name, "[green]ok[/]" if ok else "[red]fail[/]", detail)
    console.print(table)
    if not all(ok for _, ok, _ in rows):
        raise typer.Exit(code=1)
