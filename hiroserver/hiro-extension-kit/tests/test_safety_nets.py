"""The kit's part of the logging foundation's safety nets: the event loop an app starts is watched (events.bind), and
the contract's scan finds a broad `except` that drops its error."""

import asyncio
import textwrap

from hiro_commons import logging_foundation

from hiro_extension_kit import events
from hiro_extension_kit.contract import silent_catches


def test_binding_the_loop_watches_it_for_failed_tasks():
    async def main():
        events.bind()
        return asyncio.get_running_loop().get_exception_handler()

    bound = events._loop
    try:
        assert asyncio.run(main()) is logging_foundation._loop_failed
    finally:
        events._loop = bound


def test_the_scan_finds_a_catch_that_drops_its_error(tmp_path):
    (tmp_path / "app.py").write_text(textwrap.dedent('''
        import logging
        from hiro_extension_kit.errors import failed
        log = logging.getLogger("x")

        def quiet():
            try:
                work()
            except Exception:
                return None          # dropped (the first)

        def bare():
            try:
                work()
            except:                  # dropped (the second)
                pass

        def logged():
            try:
                work()
            except Exception as exc:
                failed(log, "work", exc)

        def told():
            try:
                work()
            except (ValueError, Exception):
                log.warning("work failed")

        def again():
            try:
                work()
            except BaseException:
                cleanup()
                raise

        def narrow():
            try:
                work()
            except KeyError:
                return None          # a named error is a decision, not a blind catch

        def later():
            try:
                work()
            except Exception:
                def report():        # defined here, maybe never run: not a log line
                    log.error("x")
                return report
    '''), encoding="utf-8")
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "env.py").write_text("try:\n    x()\nexcept Exception:\n    pass\n", encoding="utf-8")
    assert [line for _path, line in silent_catches(tmp_path)] == [9, 15, 46]  # quiet, bare, later
