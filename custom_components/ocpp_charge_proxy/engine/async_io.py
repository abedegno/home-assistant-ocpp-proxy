"""Join off-loop I/O before allowing cancellation to release its owner."""

import asyncio


async def offload(function, *args):
    work = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        # A canceled await cannot stop a running thread. Join it before replacement
        # setup may touch the same files, and before a resource can lose its owner.
        await asyncio.gather(work, return_exceptions=True)
        raise
