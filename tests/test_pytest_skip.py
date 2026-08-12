import itertools
import pytest

from pytest import ExitCode
from pytest_skip.plugin import Matcher
from .conftest import SELECT_OPT, DESELECT_OPT, SKIP_OPT, XFAIL_OPT

# FIXME: this needs a refactoring where we make each test a structure
# what contains the failing/passing combinations as a field
TEST_CONTENT_PASSING_COMBINATIONS = ("test_a[1-1]", "test_a[1-4]")
TEST_CONTENT_FAILING_COMBINATIONS = ("test_a[1-2]", "test_a[1-3]")

TEST_CONTENT = """
    import pytest

    @pytest.mark.parametrize(
        ('a', 'b'),
        (
            (1, 1),
            (1, 2),
            (1, 3),
            (1, 4),
        )
    )
    def test_a(a, b):
        assert b in (1, 4)
"""

TEST_CONTENT_PASS = """
    import pytest
    import itertools

    @pytest.mark.parametrize(
        ('a', 'b', 'c'),
        list(itertools.product((1, 2, 3), repeat=3))
    )
    def test_a(a, b, c):
        pass
"""

TEST_CONTENT_WITH_NESTED_BRACKETS = """
    import pytest

    @pytest.mark.parametrize(
        ('a', 'b'),
        (
            (1, 1),
            (1, 2),
            (1, 3),
            (1, 4),
        )
    )
    def test_a(a, b):
        assert b in (1, 4)

    @pytest.mark.parametrize(
        ('a', 'b'),
        (
            (1, 'a[1]'),
            (1, '2'),
            (1, '3'),
            (1, '4'),
        )
    )
    def test_b(a, b):
        assert b in ('a[1]', '4')
"""

TEST_CONTENT_WITH_REGEXP_AS_PARAM = """
    import pytest

    @pytest.mark.parametrize(
        ('a'),
        (
            "r\\"a.*\\"",
            "r\\"abc2\\""
        )
    )
    def test_a(a):
        assert True
"""


@pytest.mark.parametrize("option_name", (SELECT_OPT, DESELECT_OPT))
def test_select_options_exist(testdir, option_name):
    selection_file_name = testdir.makefile(".txt", "test_a", "test_b")
    result = testdir.runpytest(option_name, selection_file_name)

    result.assert_outcomes()
    assert result.ret == 5


@pytest.mark.parametrize("option_name", (SELECT_OPT, DESELECT_OPT))
def test_missing_selection_file_fails(testdir, option_name):
    missing_file_name = "no_such_file.txt"
    result = testdir.runpytest(option_name, missing_file_name)

    assert result.ret == 4
    result.stderr.re_match_lines(
        [f"ERROR: Given selection file '{missing_file_name}' doesn't exist."])


@pytest.mark.parametrize(
    ("select_option", "select_content", "exit_code", "outcomes", "stdout_lines"),
    (
        (None, "", 1, {
            "passed": 2,
            "failed": 2
        }, []),
        (SELECT_OPT, ["test_a[1-1]", "test_a[1-4]"], 0, {
            "passed": 2
        }, []),
        (
            SELECT_OPT,
            ["{testfile}::test_a[1-2]", "test_a[1-4]"],
            1,
            {
                "passed": 1,
                "failed": 1
            },
            [],
        ),
        (
            SELECT_OPT,
            [
                "{testfile}::test_a[1-2]",
                "test_a[1-3]",
                "test_a[3-1]",
                "test_that_does_not_exist",
            ],
            1,
            {
                "failed": 2
            },
            [
                r".*Not all tests to select exist.*",
                r"\s+Missing test names to select:",
                r"\s+- test_a\[3-1\]",
                r"\s+- test_that_does_not_exist",
            ],
        ),
        (DESELECT_OPT, ["test_a[1-1]", "test_a[1-4]"], 1, {
            "failed": 2
        }, []),
        (
            DESELECT_OPT,
            ["{testfile}::test_a[1-2]", "test_a[1-4]"],
            1,
            {
                "passed": 1,
                "failed": 1
            },
            [],
        ),
        (
            DESELECT_OPT,
            [
                "{testfile}::test_a[1-2]",
                "test_a[1-3]",
                "test_a[3-1]",
                "test_that_does_not_exist",
            ],
            0,
            {
                "passed": 2
            },
            [
                r".*Not all tests to deselect exist.*",
                r"\s+Missing test names to deselect:",
                r"\s+- test_a\[3-1\]",
                r"\s+- test_that_does_not_exist",
            ],
        ),
        (
            DESELECT_OPT,
            ["{testfile}::test_a"],
            5,
            {
                "passed": 0,
                "failed": 0
            },
            [],
        ),
        (
            SKIP_OPT,
            ["{testfile}::test_a"],
            0,
            {
                "skipped": 4
            },
            [],
        ),
        (
            SKIP_OPT,
            [
                "{testfile}::test_a[1-2]",
                "test_a[1-3]",
                "test_a[3-1]",
                "test_that_does_not_exist",
            ],
            0,
            {
                "passed": 2,
                "skipped": 2
            },
            [
                r".*Not all tests to skip exist.*",
                r"\s+Missing test names to skip:",
                r"\s+- test_a\[3-1\]",
                r"\s+- test_that_does_not_exist",
            ],
        ),
        (
            SKIP_OPT,
            ["test_a[r\"1-.*\"]@regexp"],
            0,
            {
                "skipped": 4
            },
            [],
        ),
        (
            SKIP_OPT,
            ["test_a[r\".*-[2|3]\"]@regexp"],
            0,
            {
                "passed": 2,
                "skipped": 2
            },
            [],
        ),
        (
            SKIP_OPT,
            ["{testfile}::test_a[r\".*-[2|3]\"]@regexp"],
            0,
            {
                "passed": 2,
                "skipped": 2
            },
            [],
        ),
        (
            SKIP_OPT,
            [
                "test_a[r\"1-1\"]@regexp",
                "{testfile}::test_a[r\"1-2\"]@regexp",
                "test_a[r\".*-3\"]@regexp",
            ],
            0,
            {
                "passed": 1,
                "skipped": 3
            },
            [],
        ),
        (
            XFAIL_OPT,
            ["{testfile}::test_a"],
            0,
            {
                "xfailed": 2,
                "xpassed": 2
            },
            [],
        ),
        (
            XFAIL_OPT,
            [
                "{testfile}::test_a[1-2]",
                "test_a[1-3]",
                "test_a[3-1]",
                "test_that_does_not_exist",
            ],
            0,
            {
                "passed": 2,
                "xfailed": 2
            },
            [
                r".*Not all tests to xfail exist.*",
                r"\s+Missing test names to xfail:",
                r"\s+- test_a\[3-1\]",
                r"\s+- test_that_does_not_exist",
            ],
        ),
        (
            XFAIL_OPT,
            ["test_a[r\"1-.*\"]@regexp"],
            0,
            {
                "xfailed": 2,
                "xpassed": 2
            },
            [],
        ),
        (
            XFAIL_OPT,
            ["test_a[r\".*-[2|3]\"]@regexp"],
            0,
            {
                "passed": 2,
                "xfailed": 2
            },
            [],
        ),
        (
            XFAIL_OPT,
            ["{testfile}::test_a[r\".*-[2|3]\"]@regexp"],
            0,
            {
                "passed": 2,
                "xfailed": 2
            },
            [],
        ),
        (
            XFAIL_OPT,
            [
                "test_a[r\"1-1\"]@regexp",
                "{testfile}::test_a[r\"1-2\"]@regexp",
                "test_a[r\".*-3\"]@regexp",
            ],
            0,
            {
                "passed": 1,
                "xpassed": 1,
                "xfailed": 2
            },
            [],
        ),
    ),
)
def test_tests_are_selected(  # pylint: disable=R0913, disable=R0917
    testdir,
    select_option,
    exit_code,
    select_content,
    outcomes,
    stdout_lines,
):
    testfile = testdir.makefile(".py", TEST_CONTENT)
    args = ["-v", "-Walways"]
    if select_option and select_content:
        select_file = testdir.makefile(
            ".txt",
            *[line.format(testfile=testfile.relto(testdir.tmpdir)) for line in select_content],
        )
        args.extend([select_option, select_file])
    result = testdir.runpytest(*args)

    assert result.ret == exit_code
    result.assert_outcomes(**outcomes)
    if stdout_lines:
        result.stdout.re_match_lines_random(stdout_lines)


@pytest.mark.parametrize("use_xdist", (False, True))
@pytest.mark.parametrize("has_missing_tests", (False, True))
@pytest.mark.parametrize("deselect", (False, True))
def test_fail_on_missing(is_xdist_installed, testdir, deselect, has_missing_tests, use_xdist):
    if use_xdist and not is_xdist_installed:
        pytest.skip("xdist is not installed")

    testdir.makefile(".py", TEST_CONTENT)

    existing_tests = TEST_CONTENT_FAILING_COMBINATIONS if deselect else TEST_CONTENT_PASSING_COMBINATIONS
    file_tests = ("test_a[1-1]", "test_a[2-1]") if has_missing_tests else existing_tests
    selectfile = testdir.makefile(".txt", *file_tests)
    result = testdir.runpytest(
        "-v",
        "--select-fail-on-missing",
        "-n 1" if use_xdist else "",
        f"--{'de' if deselect else ''}select-from-file",  # pylint: disable=W1405
        selectfile,
    )

    assert result.ret == (4 if has_missing_tests else 0)
    if deselect:
        first_line = r"pytest-skip: Not all tests to deselect exist."
        second_line = r"Missing test names to deselect:"
    else:
        first_line = r"pytest-skip: Not all tests to select exist."
        second_line = r"Missing test names to select:"
    if has_missing_tests:
        result.stderr.re_match_lines([
            first_line,
            second_line,
            # "  - test_a[2-1]",
        ])


@pytest.mark.parametrize(("fail_on_missing", "deselect"), [(True, False), (True, True),
                                                           (False, False), (False, True)])
def test_report_header(testdir, fail_on_missing, deselect):
    testdir.makefile(".py", TEST_CONTENT)
    selectfile = testdir.makefile(".txt", "test_a[1-1]")
    args = [
        "-v",
        f"--{'de' if deselect else ''}select-from-file",  # pylint: disable=W1405
        selectfile,
    ]
    if fail_on_missing:
        args.append("--select-fail-on-missing")
    result = testdir.runpytest(*args)

    deselect_prefix = "de" if deselect else ""
    lines = [fr"select: {deselect_prefix}selecting tests from '{selectfile}'$"]
    if fail_on_missing:
        lines.append(r"select: failing on missing selection items$")
    result.stdout.re_match_lines(lines)


@pytest.mark.parametrize(
    ("option_name", "select_content", "exit_code", "outcomes"),
    [
        (
            DESELECT_OPT,
            ["{testfile}::test_a[1-2]", "test_a[1-4]", "# Ignore comment", ""],
            1,
            {
                "passed": 1,
                "failed": 1
            },
        ),
    ],
)
def test_comment_and_blanc_lines(testdir, option_name, select_content, exit_code, outcomes):
    testfile = testdir.makefile(".py", TEST_CONTENT)
    args = ["-v", "-Walways"]
    select_file = testdir.makefile(
        ".txt",
        *[line.format(testfile=testfile.relto(testdir.tmpdir)) for line in select_content],
    )
    args.extend([option_name, select_file])
    result = testdir.runpytest(*args)

    assert result.ret == exit_code
    result.assert_outcomes(**outcomes)


@pytest.mark.parametrize(
    ("option_name", "select_content", "exit_code", "outcomes"),
    [
        (
            DESELECT_OPT,
            [
                "{testfile}::test_a[1-2]",
                "test_a[1-4]",
                "{testfile}::test_b",
                "# Smth",
                "",
            ],
            1,
            {
                "passed": 1,
                "failed": 1
            },
        ),
    ],
)
def test_nested_brackets(testdir, option_name, select_content, exit_code, outcomes):
    testfile = testdir.makefile(".py", TEST_CONTENT_WITH_NESTED_BRACKETS)
    args = ["-v", "-Walways"]
    select_file = testdir.makefile(
        ".txt",
        *[line.format(testfile=testfile.relto(testdir.tmpdir)) for line in select_content],
    )
    args.extend([option_name, select_file])
    result = testdir.runpytest(*args)

    assert result.ret == exit_code
    result.assert_outcomes(**outcomes)


@pytest.mark.parametrize(
    ("option_name", "select_content", "exit_code", "outcomes"),
    [
        (
            SKIP_OPT,
            [
                "{testfile}::test_a[r\"a.*\"]",
            ],
            0,
            {
                "passed": 1,
                "skipped": 1
            },
        ),
    ],
)
def test_with_regexp_as_param(testdir, option_name, select_content, exit_code, outcomes):
    testfile = testdir.makefile(".py", TEST_CONTENT_WITH_REGEXP_AS_PARAM)
    args = ["-v", "-Walways"]
    select_file = testdir.makefile(
        ".txt",
        *[line.format(testfile=testfile.relto(testdir.tmpdir)) for line in select_content],
    )
    args.extend([option_name, select_file])
    result = testdir.runpytest(*args)
    assert result.ret == exit_code
    result.assert_outcomes(**outcomes)


def test_xfail_reports_unexpected_pass_as_xpass(testdir):
    # A test marked xfail by pytest-skip that still passes must be reported
    # as XPASS (not PASSED), while the exit code stays green since xfail is
    # not strict by default.
    testfile = testdir.makefile(".py", TEST_CONTENT_PASS)
    xfail_file = testdir.makefile(".txt", f"{testfile.relto(testdir.tmpdir)}::test_a[1-1-1]")
    result = testdir.runpytest("-v", "-Walways", XFAIL_OPT, xfail_file)

    assert result.ret == 0
    result.assert_outcomes(passed=26, xpassed=1)
    result.stdout.re_match_lines([r".*test_a\[1-1-1\] XPASS.*"])


def test_xfail_strict_fails_run_on_unexpected_pass(testdir):
    # With --xfail-strict, an unexpected pass on a test marked xfail by pytest-skip must
    # fail the overall run (non-zero exit code), unlike the non-strict default above.
    testfile = testdir.makefile(".py", TEST_CONTENT_PASS)
    xfail_file = testdir.makefile(".txt", f"{testfile.relto(testdir.tmpdir)}::test_a[1-1-1]")
    result = testdir.runpytest("-v", "-Walways", XFAIL_OPT, xfail_file, "--xfail-strict")

    assert result.ret != 0
    result.assert_outcomes(passed=26, failed=1)
    result.stdout.re_match_lines([r".*test_a\[1-1-1\] FAILED.*"])


def test_xfail_strict_does_not_affect_expected_failures(testdir):
    # With --xfail-strict, a test that is marked xfail and genuinely fails is unaffected:
    # it is still reported as XFAILED (not FAILED), regardless of strictness. TEST_CONTENT's
    # other, unmarked failure (test_a[1-3]) still fails the run on its own, independent of
    # --xfail-strict, so the overall exit code is non-zero for an unrelated reason - the
    # point here is specifically that test_a[1-2] (the xfail-marked one) is NOT turned into
    # a failure by --xfail-strict.
    testfile = testdir.makefile(".py", TEST_CONTENT)
    xfail_file = testdir.makefile(".txt", f"{testfile.relto(testdir.tmpdir)}::test_a[1-2]")
    result = testdir.runpytest("-v", "-Walways", XFAIL_OPT, xfail_file, "--xfail-strict")

    assert result.ret != 0
    result.assert_outcomes(passed=2, failed=1, xfailed=1)
    result.stdout.re_match_lines([r".*test_a\[1-2\] XFAIL.*"])


@pytest.mark.parametrize("colliding_option", (SKIP_OPT, DESELECT_OPT))
def test_xfail_collision_with_higher_precedence_option_warns(testdir, colliding_option):
    # When a test name is listed in both --xfail-from-file and --skip-from-file (or
    # --deselect-from-file), skip/deselect wins (the xfail marker is NOT applied), but this
    # must not be a silent no-op: pytest-skip must emit an explicit warning naming the test
    # and explaining that the xfail request was dropped due to the collision.
    testfile = testdir.makefile(".py", TEST_CONTENT_PASS)
    colliding_test = f"{testfile.relto(testdir.tmpdir)}::test_a[1-1-1]"
    xfail_file = testdir.makefile(".xfail.txt", colliding_test)
    colliding_file = testdir.makefile(".colliding.txt", colliding_test)
    result = testdir.runpytest("-v", "-Walways", XFAIL_OPT, xfail_file, colliding_option,
                               colliding_file)

    assert result.ret == 0
    result.stdout.re_match_lines([
        r".*pytest-skip: '.*test_a\[1-1-1\]' matched --xfail-from-file/--xfail-test, but the "
        r"test is (deselected|skipped); the xfail marker was NOT applied.*",
    ])


@pytest.mark.parametrize("skipfile_str,is_regexp,test_name,params,", [
    ("file.py::test_name[r\"param-match\"]@regexp", True, "file.py::test_name", "param-match"),
    ("test_name[r\"param-match\"]@regexp", True, "test_name", "param-match"),
    (
        "folder/file.py::test_name[r\"some_thing\"]@regexp/something.py::test_name/folder/test.py::test_name",
        False,
        None,
        None,
    ),
    (
        "folder/file.py::test_name[r\"some_thing/something.py::test_name/folder/test.py::test_name[\"not-regexp\"]",
        False,
        None,
        None,
    ),
    ("folder/file.py::test_name[r\"some_thing\"]/something.py::test_name/folder/test.py::test_name[r\"param-match\"]@regexp",
     True,
     "folder/file.py::test_name[r\"some_thing\"]/something.py::test_name/folder/test.py::test_name",
     "param-match"), (
         "folder/file.py[r\"some_thing\"]",
         False,
         None,
         None,
     ), (
         "folder/file.py[r\"some_\"thing\"\"]@regexp",
         True,
         "folder/file.py",
         "some_\"thing\"",
     )
])
def test_regexp_match(skipfile_str, is_regexp, test_name, params):
    res_match = Matcher.regexp_test_name_pattern.match(skipfile_str)
    assert (res_match is not None) is is_regexp
    if not is_regexp:
        return

    res_test_name, res_params = res_match.groups()
    assert res_test_name == test_name
    assert res_params == params


@pytest.mark.parametrize("select", (None, ("test_a", ), ("test_a[1-1-1]", ),
                                    ("test_a[1-1-2]", "test_a[1-2-3]", "test_a[3-2-1]")))
@pytest.mark.parametrize("deselect", (("test_a", ), ("test_a[1-1-2]", "test_a[1-2-3]")))
@pytest.mark.parametrize("skip",
                         (("test_a", ), ("test_a[3-3-3]", ), ("test_a[1-2-3]", "test_a[3-2-1]")))
@pytest.mark.parametrize("use_sharding", (False, True))
def test_select_deselect_skip(testdir, select, deselect, skip, use_sharding):
    node_ids = [f"test_a[{a}-{b}-{c}]" for a, b, c in itertools.product((1, 2, 3), repeat=3)]
    testfile = testdir.makefile(".py", TEST_CONTENT_PASS)
    args = ["-v", "-Walways"]
    if use_sharding:
        args.append("--num-shards=1")
        args.append("--shard-id=0")

    def process_values(opt, values):
        if values is None:
            return set(node_ids) if opt is SELECT_OPT else set()
        sfx = "select" if opt is SELECT_OPT else "deselect" if opt is DESELECT_OPT else "skip"
        mid = len(values) // 2
        files = [
            testdir.makefile(
                f".{sfx}{i}.txt",
                l.format(testfile=testfile.relto(testdir.tmpdir)),
            ).strpath for i, l in enumerate(values[:mid])
        ]
        names = values[mid:]
        if files:
            args.extend([opt, ";".join(files)])
        if names:
            args.extend([f"{opt[:-9]}test", ";".join(names)])
        return set(node_ids) if "test_a" in values else set(values)

    select = process_values(SELECT_OPT, select)
    deselect = process_values(DESELECT_OPT, deselect)
    skip = process_values(SKIP_OPT, skip)
    deselect.intersection_update(select)
    skip.intersection_update(select)
    select.difference_update(deselect)
    skip.difference_update(deselect)
    select.difference_update(skip)

    result = testdir.runpytest(*args)
    assert result.ret == ExitCode.OK if select else ExitCode.NO_TESTS_COLLECTED
    result.assert_outcomes(passed=len(select), deselected=len(deselect), skipped=len(skip))


@pytest.mark.parametrize("select", (None, ("test_a", ), ("test_a[1-1-1]", ),
                                    ("test_a[1-1-2]", "test_a[1-2-3]", "test_a[3-2-1]")))
@pytest.mark.parametrize("deselect", (("test_a", ), ("test_a[1-1-2]", "test_a[1-2-3]")))
@pytest.mark.parametrize("skip",
                         (("test_a", ), ("test_a[3-3-3]", ), ("test_a[1-2-3]", "test_a[3-2-1]")))
@pytest.mark.parametrize("xfail",
                         (("test_a", ), ("test_a[3-3-3]", ), ("test_a[1-2-3]", "test_a[3-2-1]")))
@pytest.mark.parametrize("use_sharding", (False, True))
def test_select_deselect_skip_xfail(  # pylint: disable=R0913, disable=R0917
        testdir,
        select,
        deselect,
        skip,
        xfail,
        use_sharding,
):
    """
    Extends test_select_deselect_skip with --xfail-from-file/--xfail-test to pin down, and
    verify, the precedence decision for a name collision between xfail and
    select/deselect/skip: when a test name is matched by both xfail and deselect/skip,
    deselect/skip wins and the xfail marker is NOT applied to that test (it is either
    excluded from the run entirely, or its body never executes, so an xfail marker on it
    would be meaningless). Only names that remain selected (i.e. not deselected and not
    skipped) after that resolution get the xfail marker applied. Since the generated test
    always passes, a test that does get the xfail marker applied is reported as XPASS
    rather than PASSED.

    Reordering the skip/xfail checks, or disabling xfail marking entirely, must make this
    test fail.
    """
    node_ids = [f"test_a[{a}-{b}-{c}]" for a, b, c in itertools.product((1, 2, 3), repeat=3)]
    testfile = testdir.makefile(".py", TEST_CONTENT_PASS)
    args = ["-v", "-Walways"]
    if use_sharding:
        args.append("--num-shards=1")
        args.append("--shard-id=0")

    def process_values(opt, values):
        if values is None:
            return set(node_ids) if opt is SELECT_OPT else set()
        sfx = ("select" if opt is SELECT_OPT else
               "deselect" if opt is DESELECT_OPT else "skip" if opt is SKIP_OPT else "xfail")
        mid = len(values) // 2
        files = [
            testdir.makefile(
                f".{sfx}{i}.txt",
                l.format(testfile=testfile.relto(testdir.tmpdir)),
            ).strpath for i, l in enumerate(values[:mid])
        ]
        names = values[mid:]
        if files:
            args.extend([opt, ";".join(files)])
        if names:
            args.extend([f"{opt[:-9]}test", ";".join(names)])
        return set(node_ids) if "test_a" in values else set(values)

    select = process_values(SELECT_OPT, select)
    deselect = process_values(DESELECT_OPT, deselect)
    skip = process_values(SKIP_OPT, skip)
    xfail = process_values(XFAIL_OPT, xfail)
    deselect.intersection_update(select)
    skip.intersection_update(select)
    select.difference_update(deselect)
    skip.difference_update(deselect)
    select.difference_update(skip)

    # Precedence pinned down here: select/deselect/skip take priority over xfail on a name
    # collision, so xfail only ends up applied to names still selected after deselect/skip
    # resolution above. Any xfail name that collided with a deselected/skipped name is
    # dropped from `xfail` (mirroring the plugin's actual behavior) rather than counted.
    xfail.intersection_update(select)
    select.difference_update(xfail)

    result = testdir.runpytest(*args)
    # A test is still "collected" (contributing to a normal, non-NO_TESTS_COLLECTED exit)
    # if it ends up passed, skipped, or xpassed, only full deselection empties the run.
    # skip/xfail never remove an item from collection, they just change how it's reported.
    assert result.ret == (ExitCode.OK if (select or skip or xfail) else ExitCode.NO_TESTS_COLLECTED)
    result.assert_outcomes(
        passed=len(select),
        deselected=len(deselect),
        skipped=len(skip),
        xpassed=len(xfail),
    )
