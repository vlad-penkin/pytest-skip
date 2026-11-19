import pytest

from pytest import ExitCode
from .conftest import DESELECT_OPT, SKIP_OPT, XFAIL_OPT

XFAIL_NORUN_OPT = "--xfail-norun-from-file"

TEST_CONTENT_SKIP_MARKS = """
    import pathlib
    import pytest

    BODY_RAN = pathlib.Path(__file__).with_name("body_ran")

    @pytest.fixture
    def touch():
        BODY_RAN.touch()

    @pytest.mark.skipif(True, reason="own skipif")
    def test_skipif(touch):
        BODY_RAN.touch()

    @pytest.mark.skip(reason="own skip")
    def test_skip(touch):
        BODY_RAN.touch()

    @pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.skip(reason="param skip"))])
    def test_param(touch, x):
        BODY_RAN.touch()

    @pytest.mark.skip(reason="class skip")
    class TestClass:
        def test_method(self, touch):
            BODY_RAN.touch()

    @pytest.mark.skip(reason="not listed")
    def test_unlisted():
        pass
"""

TEST_CONTENT_MODULE_SKIP = """
    import pathlib
    import pytest

    pytestmark = pytest.mark.skipif(True, reason="module skipif")

    def test_module_mark():
        pathlib.Path(__file__).with_name("body_ran").touch()
"""

SKIP_MARKED_TESTS = ("test_marks.py::test_skipif", "test_marks.py::test_skip",
                     "test_marks.py::test_param", "test_marks.py::TestClass::test_method",
                     "test_module.py::test_module_mark")


@pytest.mark.parametrize("use_xdist", (False, True))
@pytest.mark.parametrize("overrides_skip", (False, True))
def test_xfail_overrides_skip(is_xdist_installed, testdir, overrides_skip, use_xdist):
    # With the flag, listed tests whose own, class or module skip marks are true are XFAIL and
    # run neither fixtures nor body; an unlisted skip-marked test stays SKIPPED. Without it,
    # skip marks win as before.
    if use_xdist and not is_xdist_installed:
        pytest.skip("xdist is not installed")
    testdir.makepyfile(test_marks=TEST_CONTENT_SKIP_MARKS, test_module=TEST_CONTENT_MODULE_SKIP)
    args = [
        "-v", "-rxs", "-Walways", "--select-fail-on-missing", XFAIL_NORUN_OPT,
        testdir.makefile(".txt", *SKIP_MARKED_TESTS)
    ]
    if overrides_skip:
        args.append("--xfail-overrides-skip")
    if use_xdist:
        args.append("-n 1")
    result = testdir.runpytest(*args)

    assert result.ret == ExitCode.OK
    assert not testdir.tmpdir.join("body_ran").exists()
    if overrides_skip:
        result.assert_outcomes(xfailed=5, skipped=1)
        result.stdout.re_match_lines_random([r"select: xfail-norun overriding skip marks$"] + [
            fr".*XFAIL .*{name}.* - \[NOTRUN\] Xfailed by pytest-skip$"
            for name in ("test_skipif", "test_skip", r"test_param\[1\]", "test_method",
                         "test_module_mark")
        ])
    else:
        result.assert_outcomes(skipped=6)
        result.stdout.no_re_match_line(r"select: xfail-norun overriding skip marks")


def test_xfail_overrides_skip_yields_to_runxfail(testdir):
    # --runxfail turns xfail marks off, so the test's own skip mark applies again.
    testdir.makepyfile(test_marks=TEST_CONTENT_SKIP_MARKS)
    result = testdir.runpytest("-v", "--runxfail", "--xfail-overrides-skip", XFAIL_NORUN_OPT,
                               testdir.makefile(".txt", "test_marks.py::test_skipif"))

    assert result.ret == ExitCode.OK
    result.assert_outcomes(skipped=5)
    assert not testdir.tmpdir.join("body_ran").exists()


@pytest.mark.parametrize("colliding_option", (SKIP_OPT, DESELECT_OPT))
def test_xfail_overrides_skip_yields_to_skip_and_deselect_lists(testdir, colliding_option):
    # A name also in a skip or deselect list keeps the 0.3.0 precedence and warning with the flag.
    testdir.makepyfile(test_marks=TEST_CONTENT_SKIP_MARKS)
    name = "test_marks.py::test_skipif"
    result = testdir.runpytest("-v", "-Walways", "--xfail-overrides-skip", XFAIL_NORUN_OPT,
                               testdir.makefile(".norun.txt", name), colliding_option,
                               testdir.makefile(".colliding.txt", name))

    assert result.ret == ExitCode.OK
    if colliding_option is SKIP_OPT:
        reason = "skipped"
        result.assert_outcomes(skipped=5)
    else:
        reason = "deselected"
        result.assert_outcomes(skipped=4, deselected=1)
    result.stdout.re_match_lines([
        fr".*pytest-skip: '{name}' matched --xfail-norun-from-file/--xfail-norun-test, but the "
        fr"test is {reason}; the xfail\(run=False\) marker was NOT applied.*",
    ])


def test_xfail_overrides_skip_with_sharding(testdir):
    # Round-robin shard 0 of 2 over the 5 collected tests keeps test_skipif, test_param[1] and
    # test_unlisted: the 2 listed ones are XFAIL, the unlisted one stays SKIPPED.
    testdir.makepyfile(test_marks=TEST_CONTENT_SKIP_MARKS)
    result = testdir.runpytest("-v", "-Walways", "--select-fail-on-missing",
                               "--xfail-overrides-skip", XFAIL_NORUN_OPT,
                               testdir.makefile(".txt", *SKIP_MARKED_TESTS[:4]), "--num-shards=2",
                               "--shard-id=0")

    assert result.ret == ExitCode.OK
    result.assert_outcomes(xfailed=2, skipped=1, deselected=2)
    assert not testdir.tmpdir.join("body_ran").exists()


TEST_CONTENT_LATE_SKIPS = """
    import pathlib
    import pytest

    BODY_RAN = pathlib.Path(__file__).with_name("body_ran")

    def test_conftest_skip():
        BODY_RAN.touch()

    @pytest.mark.skipif("True", reason="string condition")
    def test_string_condition():
        BODY_RAN.touch()

    @pytest.mark.skipif("undefined_name", reason="raising condition")
    def test_raising_condition():
        BODY_RAN.touch()
"""

CONFTEST_ADDS_SKIP = """
    import pytest

    def pytest_collection_modifyitems(items):
        for item in items:
            if item.name == "test_conftest_skip":
                item.add_marker(pytest.mark.skip(reason="conftest skip"))
"""


@pytest.mark.parametrize("overrides_skip", (False, True))
def test_xfail_overrides_skip_conftest_and_condition_marks(testdir, overrides_skip):
    # A skip mark a conftest adds after collection and skipif string conditions are overridden
    # too. Marks are not evaluated with the flag, so a raising condition gives XFAIL, not ERROR.
    testdir.makeconftest(CONFTEST_ADDS_SKIP)
    testdir.makepyfile(test_late=TEST_CONTENT_LATE_SKIPS)
    args = [
        "-v", "--select-fail-on-missing", XFAIL_NORUN_OPT,
        testdir.makefile(".txt", "test_conftest_skip", "test_string_condition",
                         "test_raising_condition")
    ]
    if overrides_skip:
        args.append("--xfail-overrides-skip")
    result = testdir.runpytest(*args)

    assert not testdir.tmpdir.join("body_ran").exists()
    if overrides_skip:
        assert result.ret == ExitCode.OK
        result.assert_outcomes(xfailed=3)
    else:
        assert result.ret == ExitCode.TESTS_FAILED
        result.assert_outcomes(skipped=2, errors=1)


TEST_CONTENT_TEARDOWN_ERROR = """
    import pytest

    @pytest.fixture(scope="module")
    def resource():
        yield
        raise RuntimeError("module teardown failed")

    def test_uses_resource(resource):
        pass

    def test_listed():
        pass
"""


@pytest.mark.parametrize("overrides_skip", (False, True))
def test_xfail_overrides_skip_keeps_tests_without_skip_marks(testdir, overrides_skip):
    # A listed test with no skip mark is left to pytest with the flag. Here the module fixture's
    # teardown error is charged to test_listed, and pytest reports it as a second XFAIL either way.
    testdir.makepyfile(test_teardown=TEST_CONTENT_TEARDOWN_ERROR)
    args = ["-v", XFAIL_NORUN_OPT, testdir.makefile(".txt", "test_teardown.py::test_listed")]
    if overrides_skip:
        args.append("--xfail-overrides-skip")
    result = testdir.runpytest(*args)

    assert result.ret == ExitCode.OK
    result.assert_outcomes(passed=1, xfailed=2)


def test_xfail_overrides_skip_ignores_xfail_with_run(testdir):
    # The flag applies only to xfail-norun: an --xfail-from-file entry keeps its skip.
    testdir.makepyfile(test_marks=TEST_CONTENT_SKIP_MARKS)
    result = testdir.runpytest("-v", "--xfail-overrides-skip", XFAIL_OPT,
                               testdir.makefile(".txt", "test_marks.py::test_skipif"))

    assert result.ret == ExitCode.OK
    result.assert_outcomes(skipped=5)
    assert not testdir.tmpdir.join("body_ran").exists()
