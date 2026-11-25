"""Low-level KMS recovery commands; not a complete deployment procedure.

The operator must stop every writer and prevent concurrent rotations first.
The journal contains secret keys and must be stored on a private filesystem.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.crypto.master_key_coordinator import (
    abort_incomplete_preparation,
    apply_rotation,
    finalize_rollback,
    finalize_rotation,
    prepare_rotation,
    rollback_rotation,
)


async def perform_action(
    action: str, factory: async_sessionmaker[AsyncSession], env_path: Path, journal: Path
) -> int | None:
    """Dispatch one journal operation; caller owns writer isolation and recovery."""
    if action == "prepare":
        prepare_rotation(env_path, journal)
    elif action == "apply":
        return await apply_rotation(factory, env_path, journal)
    elif action == "rollback":
        await rollback_rotation(factory, env_path, journal)
    elif action == "finalize":
        await finalize_rotation(factory, env_path, journal)
    elif action == "finalize-rollback":
        await finalize_rollback(factory, env_path, journal)
    elif action == "abort-incomplete":
        await abort_incomplete_preparation(factory, env_path, journal)
    else:
        raise ValueError("Unknown KMS rotation action")
    return None


async def _run(action: str, env_path: Path, journal: Path) -> None:
    import app.models  # noqa: F401 - register ORM relationships
    from app.core.database import close_engine, get_session_factory

    try:
        count = await perform_action(action, get_session_factory(), env_path, journal)
        print(f"KMS action {action} completed" + (f"; keys={count}" if count is not None else ""))
    finally:
        await close_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "apply",
            "rollback",
            "finalize",
            "finalize-rollback",
            "abort-incomplete",
        ),
    )
    parser.add_argument("--env-path", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_path.is_absolute() or not args.journal.is_absolute():
        parser.error("environment and journal paths must be absolute")
    asyncio.run(_run(args.action, args.env_path, args.journal))


if __name__ == "__main__":
    main()
