"""Build the application service from settings (used by the API server and the CLI)."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass

from jevmem.config import Settings
from jevmem.database.repository import SqlMemoryStore, TurnStore
from jevmem.database.session import init_db, make_engine, make_sessionmaker
from jevmem.judgment.jev_judge import JevJudge
from jevmem.memory.service import MemoryService
from jevmem.observability.logging import get_logger
from jevmem.observability.metrics import Metrics
from jevmem.providers.cache import ResponseCache
from jevmem.providers.factory import build_jev_client, build_qwen_provider
from jevmem.providers.jev import SystemOneClient
from jevmem.providers.qwen import OpenAICompatibleProvider
from jevmem.retrieval.embedding import Embedder, EmbeddingCache, SentenceTransformerEmbedder

log = get_logger("bootstrap")


@dataclass
class App:
    service: MemoryService
    stack: AsyncExitStack
    jev_client: SystemOneClient | None
    qwen: OpenAICompatibleProvider | None

    async def aclose(self) -> None:
        await self.stack.aclose()


def _embedder(settings: Settings) -> Embedder | None:
    if not settings.embeddings_enabled:
        return None
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        log.info("embeddings extra not installed; embedding and dense-hybrid retrieval disabled")
        return None
    cache = EmbeddingCache(settings.data_dir / "cache" / "embeddings.sqlite3")
    return SentenceTransformerEmbedder(settings.embedding_model, cache=cache, cache_queries=True)


async def build_app(settings: Settings, *, response_cache: bool = True) -> App:
    from jevmem.benchmark.runner import load_params

    stack = AsyncExitStack()
    engine = make_engine(settings.database_url)
    init_db(engine)
    stack.callback(engine.dispose)
    sessions = make_sessionmaker(engine)

    cache = None
    if response_cache:
        cache = ResponseCache(settings.data_dir / "cache" / "app-responses.sqlite3")
        stack.callback(cache.close)

    jev_client = qwen = None
    judge = None
    if settings.jev_api_key is not None:
        jev_client = await stack.enter_async_context(build_jev_client(settings, cache))
        judge = JevJudge(jev_client)
    if settings.qwen_base_url and settings.qwen_model:
        qwen = await stack.enter_async_context(build_qwen_provider(settings, cache))

    params = load_params(settings.params_path)
    service = MemoryService(
        settings,
        SqlMemoryStore(sessions),
        TurnStore(sessions),
        judge=judge,
        generator=qwen,
        embedder=_embedder(settings),
        policy=params.policy.get("jev") or params.policy[next(iter(params.policy))],
        top_k={
            "recency": params.k["recency"],
            "bm25": params.k["bm25"],
            "embedding": params.k["embedding"],
        },
        metrics=Metrics(),
        clients={k: v for k, v in (("jev", jev_client), ("qwen", qwen)) if v is not None},
    )
    return App(service=service, stack=stack, jev_client=jev_client, qwen=qwen)
