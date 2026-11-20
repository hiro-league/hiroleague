"""The shared silent-catch scan: a broad `except` that neither logs nor raises again is found; the apps' contract,
Code reports and the core's own tests all run it."""

import textwrap

from hiro_commons.logging_foundation.catches import silent_catches


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


def test_a_packages_own_logging_helper_counts_and_tests_can_be_left_out(tmp_path):
    (tmp_path / "worker.py").write_text(textwrap.dedent("""
        def run():
            try:
                work()
            except Exception as exc:
                report("worker", exc)
    """), encoding="utf-8")
    (tmp_path / "test_worker.py").write_text("try:\n    x()\nexcept Exception:\n    pass\n", encoding="utf-8")
    assert [p.name for p, _l in silent_catches(tmp_path)] == ["test_worker.py", "worker.py"]
    assert silent_catches(tmp_path, tests=False, log_calls=("report",)) == []
