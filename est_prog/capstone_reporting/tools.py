"""Awaitable reporting tools over the current synthetic backend.

The agent depends on these async signatures. A future HTTP/API backend can
replace the bodies with awaited requests without changing the agent protocol.
Local file reads run in a worker thread; arithmetic remains in defects.py.
"""
import asyncio

from . import defects


async def get_defect_summary(section=None, date_from=None, date_to=None):
    return await asyncio.to_thread(
        defects.get_defect_summary, section=section, date_from=date_from, date_to=date_to,
    )


async def get_defect_detail(section=None, date_from=None, date_to=None):
    return await asyncio.to_thread(
        defects.get_defect_detail, section=section, date_from=date_from, date_to=date_to,
    )


async def get_defect_pareto(section=None, date_from=None, date_to=None,
                          metric="removed_boards"):
    return await asyncio.to_thread(
        defects.get_defect_pareto, section=section, date_from=date_from, date_to=date_to,
        metric=metric,
    )
