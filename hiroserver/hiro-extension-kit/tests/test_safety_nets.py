"""The kit's part of the logging foundation's safety nets: the event loop an app starts is watched (events.bind). (The
contract's silent-catch scan is the shared one: hiro-commons' test_catches.py.)"""

import asyncio

from hiro_commons import logging_foundation

from hiro_extension_kit import events


def test_binding_the_loop_watches_it_for_failed_tasks():
    async def main():
        events.bind()
        return asyncio.get_running_loop().get_exception_handler()

    bound = events._loop
    try:
        assert asyncio.run(main()) is logging_foundation._loop_failed
    finally:
        events._loop = bound
