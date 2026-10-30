import re
import functools
from typing import Optional
import pytest

from .conftest import SELECT_OPT, DESELECT_OPT, SKIP_OPT, XFAIL_OPT


@functools.lru_cache
def generate_test(num_cases: int, test_name: str = "test_a") -> str:
    if num_cases == 0:
        return "import pytest"

    test_content = """
import pytest

@pytest.mark.parametrize(
    'a', [{cases}]
)
def {test_name}(a):
    assert True
    """
    cases = ",".join(map(str, range(num_cases)))
    return test_content.format(cases=cases, test_name=test_name)


def parse_param_names(test_names: dict[str, list[str]], ) -> dict[str, dict[str, list[str]]]:
    """
    Extract params from test names in a grouped dictionary.

    Example fn's input: {
        "GROUP_A": ["file.py::test[1]", "file.py::test[2]"],
        "GROUP_B": ["file.py::test_without_params"]
    }

    Example fn's output: {
        "GROUP_A": {"file.py::test": ["1", "2"]},
        "GROUP_B": {"file.py::test_without_params": []}
    }
    """
    regexp = re.compile(r"^(.*?)\[(.+)\]$")
    result = {}
    for group, tests in test_names.items():
        group_res: dict[str, list[str]] = {}
        for line in tests:
            match = re.match(regexp, line)
            if match is None:
                # test with no parameters
                group_res[line] = []
                continue
            test_name, param = match.groups()
            params = group_res.get(test_name, [])
            params.append(param)
            group_res[test_name] = params
        result[group] = group_res
    return result


def extract_test_names(outlines: list[str]) -> dict[str, list[str]]:
    """
    Extract test names from pytest output.

    Example fn's output: {
        "FAILED": ["file.py::test_no_params"],
        "PASSED": ["file.py::test[1-1]", "file.py::test[1-2]", "file.py::test_2[param1]"],
        "SKIPPED": ["file.py::test_2[param2]", "file.py::test_2[param3]"],
    }
    """
    regexp = re.compile(r"^(.*) (FAILED|PASSED|SKIPPED|XPASS).*\[\s*\d+%\]$")
    test_names: dict[str, list[str]] = {"FAILED": [], "PASSED": [], "SKIPPED": [], "XPASS": []}
    for line in outlines:
        line = line.strip()
        match = re.match(regexp, line)
        if match is None:
            continue
        names = test_names[match.groups()[1]]
        names.append(match.groups()[0])
    return test_names


def parse_tests_by_status(outlines: list[str]) -> dict["str", dict[str, list[str]]]:
    """
    Parse pytest-output and extract test names with their parameter combinations
    combined by the test status (PASSED, FAILED, SKIPPED).

    Example fn's output: {
        "FAILED": {"file.py::test_no_params": []},
        "PASSED": {"file.py::test": ["1-1", "1-2"], "file.py::test_2": ["param1"]},
        "SKIPPED": {"file.py::test_2": ["param2", "param3"]},
    }
    """
    test_names = extract_test_names(outlines)
    return parse_param_names(test_names)


def merge_list_dicts(out1: dict[str, list], out2: dict[str, list]) -> dict[str, list]:
    """
    Merge two dictionaries having lists as their value.

    Example:
    >>> merge_list_dicts(out1={"A": [1, 2]}, out2={"A": [1, 3], "B": [4]})
    {"A": [1, 2, 1, 3], "B": [4]}
    """
    for key, value in out2.items():
        if key in out1:
            new_value = out1[key] + value
        else:
            new_value = value
        out1[key] = new_value
    return out1


def assert_sharding(  # pylint: disable=too-many-arguments, too-many-locals, too-many-positional-arguments
    testdir,
    num_not_passed_per_shard: dict,
    num_selected: int,
    num_shards: int,
    test_name: str,
    extra_pytest_args: Optional[list] = None,
    passed_tests_per_shard: Optional[list[str]] = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Run pytest with sharding and (optionally) extra CLI args per shard.

    Returns a 2-tuple:
      - a dictionary with passed-or-xpassed tests as a key and their parameters as a value
        (XPASS is folded into this bucket since, from a "did the shard select/run it"
        perspective, both are part of the selected/executed tests).
        Output example: {"file.py::test": ["1", "2"], "file.py::test_2": ["1-1", "1-2"]}
      - a dictionary with only the xpassed tests, in the same shape, so callers can verify
        which (if any) specific tests were actually marked xfail and unexpectedly passed,
        rather than only the merged/aggregate count.
    """
    combined_outputs: dict[str, list[str]] = {}
    combined_xpass: dict[str, list[str]] = {}

    if num_selected > num_shards:
        shard_sizes = {
            num_selected // num_shards,
            num_selected // num_shards + 1,
        }
    else:
        shard_sizes = {1}

    for shard_id in range(num_shards):
        args = ["-v", "--num-shards", str(num_shards), "--shard-id", str(shard_id)]
        if extra_pytest_args is not None:
            args += extra_pytest_args
        result = testdir.runpytest(*args)

        is_empty_shard = num_shards > num_selected and shard_id >= num_selected
        # ret==5 means "no tests collected"
        assert result.ret == 0 or (result.ret == 5 and is_empty_shard)

        grouped = parse_tests_by_status(result.outlines)
        assert len(grouped["FAILED"].get(test_name,
                                         [])) == num_not_passed_per_shard.get("FAILED", 0)
        assert len(grouped["SKIPPED"].get(test_name,
                                          [])) == num_not_passed_per_shard.get("SKIPPED", 0)
        # Tests marked xfail by pytest-skip that still pass are reported as
        # XPASS rather than PASSED, but they are still part of the shard's
        # selected/executed tests, so fold them back in here.
        out = merge_list_dicts(dict(grouped["PASSED"]), grouped["XPASS"])
        combined_xpass = merge_list_dicts(combined_xpass, dict(grouped["XPASS"]))

        if len(out) == 0:
            assert is_empty_shard
            continue

        # assert that all tests are unique
        assert len(out[test_name]) == len(set(out[test_name]))

        num_passed_in_this_shard = len(out[test_name])
        assert num_passed_in_this_shard in shard_sizes

        if passed_tests_per_shard is not None:
            tests_per_shard = passed_tests_per_shard[shard_id]
            assert len(tests_per_shard) == len(set(tests_per_shard))
            assert set(out[test_name]) == set(tests_per_shard)

        combined_outputs = merge_list_dicts(combined_outputs, out)

    return combined_outputs, combined_xpass


# ===== Tests =====


@pytest.mark.parametrize("num_tests", [0, 1, 8, 13, 16])
@pytest.mark.parametrize("num_shards", [1, 5, 8, 15, 16])
@pytest.mark.parametrize("sharding_mode", ["contiguous-split", "round-robin"])
def test_even_sharding(testdir, num_tests, num_shards, sharding_mode):
    case_name = "test_a"
    test_content = generate_test(num_tests, case_name)
    testdir.makefile(".py", test_content)
    test_name = f"test_even_sharding.py::{case_name}"

    combined_outputs, combined_xpass = assert_sharding(
        testdir,
        num_not_passed_per_shard={
            "FAILED": 0,
            "SKIPPED": 0
        },
        num_selected=num_tests,
        num_shards=num_shards,
        test_name=test_name,
        extra_pytest_args=[
            "--sharding-mode",
            sharding_mode,
        ],
    )

    # No xfail option is used here, so no test should ever surface as XPASS.
    assert not combined_xpass

    if len(combined_outputs) == 0:
        assert num_tests == 0
        return

    assert len(combined_outputs[test_name]) == num_tests

    test_set = set(combined_outputs[test_name])
    assert len(test_set) == num_tests

    # verify that all tests (parameters combinations) were ran
    assert test_set == set(map(str, range(num_tests)))


@pytest.mark.parametrize("select_option", [SELECT_OPT, DESELECT_OPT, SKIP_OPT, XFAIL_OPT])
@pytest.mark.parametrize("sharding_mode", ["contiguous-split", "round-robin"])
def test_tests_are_selected_with_sharding(testdir, select_option, sharding_mode):  # pylint: disable=too-many-locals
    num_tests = 32
    num_shards = 5

    select_cases = ["0", "1", "2", "3", "4", "16", "17", "31"]
    case_name = "test_a"
    select_content = [f"{case_name}[{case}]" for case in select_cases]
    test_name = f"test_tests_are_selected_with_sharding.py::{case_name}"

    test_content = generate_test(num_tests, case_name)

    if select_option == SELECT_OPT:
        num_selected_tests = len(select_cases)
        passed_cases = select_cases
    elif select_option in (DESELECT_OPT, SKIP_OPT):
        num_selected_tests = num_tests - len(select_cases)
        passed_cases = set(map(str, range(num_tests))) - set(select_cases)
    elif select_option == XFAIL_OPT:
        # xfail doesn't remove tests from the run (unlike deselect/skip), it
        # only marks the matched ones as expected-to-fail. Since the
        # generated test always passes, those marked tests are still
        # selected and sharded as usual, they just surface as XPASS instead
        # of PASSED.
        num_selected_tests = num_tests
        passed_cases = set(map(str, range(num_tests)))
    else:
        assert False, f"Unknown select option: {select_option}"

    testfile = testdir.makefile(".py", test_content)
    select_file = testdir.makefile(
        ".txt",
        *[line.format(testfile=testfile.relto(testdir.tmpdir)) for line in select_content],
    )

    combined_passed, combined_xpass = assert_sharding(
        testdir,
        num_not_passed_per_shard={
            "FAILED": 0,
            # each shard skippes all the tests in a skiplist
            "SKIPPED": 0 if select_option != SKIP_OPT else len(select_cases),
        },
        num_selected=num_selected_tests,
        num_shards=num_shards,
        test_name=test_name,
        extra_pytest_args=[select_option, select_file, "--sharding-mode", sharding_mode],
    )

    # This is the crux of xfail-under-sharding coverage: it's not enough for the
    # aggregate pass-count to be unchanged (that would hold identically whether xfail
    # marking under sharding works, is broken, or was never wired in at all). Assert that
    # the XPASS bucket actually contains exactly the xfail-matched test names when
    # --xfail-from-file is used, and is empty for every other option.
    if select_option == XFAIL_OPT:
        assert combined_xpass[test_name]
        assert set(combined_xpass[test_name]) == set(select_cases)
    else:
        assert not combined_xpass

    if len(combined_passed) == 0:
        assert num_tests == 0
        return

    assert len(combined_passed[test_name]) == num_selected_tests
    test_set = set(combined_passed[test_name])
    assert len(test_set) == num_selected_tests

    # verify that all tests (parameters combinations) were ran
    assert test_set == set(passed_cases)


@pytest.mark.parametrize(
    ("mode", "tests_per_shard"),
    [
        ("round-robin", [
            ["0", "4", "8", "12"],
            ["1", "5", "9", "13"],
            ["2", "6", "10", "14"],
            ["3", "7", "11", "15"],
        ]),
        ("contiguous-split", [
            ["0", "1", "2", "3"],
            ["4", "5", "6", "7"],
            ["8", "9", "10", "11"],
            ["12", "13", "14", "15"],
        ]),
    ],
)
def test_sharding_modes(testdir, mode, tests_per_shard):
    num_tests = 16
    num_shards = 4

    case_name = "test_a"
    test_content = generate_test(num_tests, case_name)
    test_name = f"test_sharding_modes.py::{case_name}"
    testdir.makefile(".py", test_content)

    combined_outputs, combined_xpass = assert_sharding(
        testdir,
        num_not_passed_per_shard={
            "FAILED": 0,
            "SKIPPED": 0
        },
        num_selected=num_tests,
        num_shards=num_shards,
        test_name=test_name,
        extra_pytest_args=[
            "--sharding-mode",
            mode,
        ],
        passed_tests_per_shard=tests_per_shard,
    )

    # No xfail option is used here, so no test should ever surface as XPASS.
    assert not combined_xpass

    if len(combined_outputs) == 0:
        assert num_tests == 0
        return

    assert len(combined_outputs[test_name]) == num_tests

    test_set = set(combined_outputs[test_name])
    assert len(test_set) == num_tests

    # verify that all tests (parameters combinations) were ran
    assert test_set == set(map(str, range(num_tests)))
