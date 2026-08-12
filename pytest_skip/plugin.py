from enum import Enum
from typing import ClassVar, Dict, List, Literal, Optional, Pattern, Set, Union
from dataclasses import dataclass, field
import warnings
from pathlib import Path
import re
import importlib.metadata

import pytest
from pytest import UsageError


class SelectOption(Enum):
    SELECT = ("selectfromfile", "selecttest")
    DESELECT = ("deselectfromfile", "deselecttest")
    SKIP = ("skipfromfile", "skiptest")
    XFAIL = ("xfailfromfile", "xfailtest")


@dataclass
class Matcher:
    test_names: Dict[str, Union[Literal[True], Set[Pattern]]] = field(default_factory=dict)
    seen_test_names: Set[str] = field(default_factory=set)

    regexp_test_name_suffix: ClassVar[str] = "@regexp"
    regexp_test_name_pattern: ClassVar[Pattern] = re.compile(r"^(.+)\[r\"(.*?)\"\]@regexp$")
    test_name_pattern: ClassVar[Pattern] = re.compile(r"^(.+?)\[(.*)\]$")

    def add(self, test_name: str):
        # Check if the line has the regexp suffix before matching
        # the whole pattern. Saves time on huge skip-lists
        if test_name.endswith(self.regexp_test_name_suffix):
            match = self.regexp_test_name_pattern.match(test_name)
            if match is None:
                warnings.warn(f"The line '{test_name}' has athe @regexp "
                              "suffix but doesn't contain an actual regexp. The line will be "
                              "treated as a non-regexp.")
                self.test_names[test_name[:-len(self.regexp_test_name_suffix)]] = True
            else:
                test_name, regexp = match.groups()
                regexps_list = self.test_names.get(test_name, set())
                if regexps_list is True:
                    warnings.warn(
                        f"The test {test_name} appears as a regexp and non-regexp! Ignoring the regexp version."
                    )
                    return
                regexps_list.add(re.compile(regexp))
                self.test_names[test_name] = regexps_list
        else:
            self.test_names[test_name] = True

    def add_from_file(self, file_path: str):
        path = Path(file_path)
        if not path.exists():
            raise UsageError(f"Given selection file '{file_path}' doesn't exist.")
        with path.open("rt", encoding="UTF-8") as lines:
            for line in lines:
                if (line := line.strip()) and not line.startswith("#"):
                    self.add(line)

    def match_name(self, name: str) -> bool:
        if ((matches := self.test_names.get(name, None)) is None and name[-1] == "]"
                and (match := self.test_name_pattern.match(name)) is not None):
            name, params = match.groups()
            matches = self.test_names.get(name, None)
        else:
            params = ""
        if isinstance(matches, set):
            matches = any(m.match(params) for m in matches)  # type: ignore[assignment]
        if matches:
            self.seen_test_names.add(name)
            return True
        return False

    def match_item(self, item: pytest.Item) -> bool:
        return self.match_name(item.nodeid) or self.match_name(item.name)


@dataclass
class ShardingConfig:

    class ShardingMode(Enum):
        CONTIGUOUS_SPLIT = "contiguous-split"
        ROUND_ROBIN = "round-robin"

    num_shards: int
    shard_id: int
    mode: ShardingMode
    items_weights: Optional[dict[str, float]]

    def _round_robin_sharding(self, selected_items: list[str], deselected_items: list[str]):
        # Round-robin sharding distributes tests evenly across shards.
        if self.shard_id >= len(selected_items):
            deselected_items.extend(selected_items)
            return [], deselected_items

        deselected_items.extend(
            [item for i, item in enumerate(selected_items) if i % self.num_shards != self.shard_id])
        selected_items = [
            item for i, item in enumerate(selected_items) if i % self.num_shards == self.shard_id
        ]
        return selected_items, deselected_items

    def _contiguous_even_sharding(self, selected_items: list[str], deselected_items: list[str]):
        total = len(selected_items)
        base_size = total // self.num_shards
        remainder = total % self.num_shards

        start = self.shard_id * base_size + min(self.shard_id, remainder)
        end = start + base_size + (1 if self.shard_id < remainder else 0)

        deselected_items.extend(selected_items[:start] + selected_items[end:])
        selected_items = selected_items[start:end]

        return selected_items, deselected_items

    def _even_sharding(self, selected_items: list[str], deselected_items: list[str]):
        if self.mode == self.ShardingMode.ROUND_ROBIN.value:
            return self._round_robin_sharding(selected_items, deselected_items)
        if self.mode == self.ShardingMode.CONTIGUOUS_SPLIT.value:
            return self._contiguous_even_sharding(selected_items, deselected_items)
        raise ValueError(f"Unsupported sharding mode: {self.mode}")

    def _weighted_sharding(self, selected_items: list[str], deselected_items: list[str]):
        # TODO: implement
        raise NotImplementedError("Sharding with weights is not supported yet.")

    @classmethod
    def _parse_weights(cls, weights_filepath):
        # TODO: implement
        raise NotImplementedError("Sharding with weights is not supported yet.")

    def do_sharding(self, selected_items: list[str], deselected_items: list[str]):
        if self.items_weights is not None:
            return self._weighted_sharding(selected_items, deselected_items)
        return self._even_sharding(selected_items, deselected_items)

    @classmethod
    def from_config(cls, config: pytest.Config) -> Optional["ShardingConfig"]:
        num_shards = config.getoption("num_shards")
        shard_id = config.getoption("shard_id")
        mode = config.getoption("sharding_mode").lower().strip()

        allowed_modes = {m.value for m in cls.ShardingMode}
        if mode not in allowed_modes:
            allowed_modes_str = ", ".join(allowed_modes)
            raise ValueError(f"Invalid sharding mode: {mode}. Available modes: {allowed_modes_str}")
        # weights_filepath = config.getoption("shard_weights_file")
        weights_filepath = None

        items_weights = None
        if weights_filepath:
            items_weights = cls._parse_weights(weights_filepath)

        if (num_shards is None) != (shard_id is None):
            num_shards = None
            shard_id = None
            warnings.warn(
                UserWarning(
                    "Sharding is ignored: you have to specify both '--num-shards' and '--shard-id'")
            )

        if num_shards is None and shard_id is None:
            return None

        try:
            num_shards = int(num_shards)
            shard_id = int(shard_id)
        except ValueError as err:
            raise ValueError("Invalid sharding configuration. '--num-shards' and '--shard-id' "
                             f"must be integers: {err}") from err

        if num_shards <= 0:
            raise ValueError(f"{num_shards} must be a positive number")

        if shard_id >= num_shards or shard_id < 0:
            raise ValueError(f"{shard_id=} must be positive and less than {num_shards=}")

        sharding_config = None
        if num_shards is not None and shard_id is not None:
            sharding_config = ShardingConfig(num_shards, shard_id, mode, items_weights)
        return sharding_config


@dataclass
class SelectConfig:
    select: Optional[Matcher]
    deselect: Optional[Matcher]
    skip: Optional[Matcher]
    xfail: Optional[Matcher]
    fail_on_missing: bool

    def check_missing_tests(self):
        for n, m in self.get_matchers().items():
            if (missing := set(m.test_names.keys()) - m.seen_test_names):
                # If any items remain in `test_names` those tests either don't exist or
                # have been deselected by another way - warn user
                message = (f"\npytest-skip: Not all tests to {n} exist.\n"
                           f"Missing test names to {n}:\n  - ")
                message += "\n  - ".join(missing)
                if self.fail_on_missing:
                    raise UsageError(message)
                warnings.warn(UserWarning(message))

    @classmethod
    def from_config(cls, config: pytest.Config) -> Optional["SelectConfig"]:
        fail_on_missing = config.getoption("selectfailonmissing")
        matchers: Dict[SelectOption, Optional[Matcher]] = {o: None for o in SelectOption}
        for option in SelectOption:
            for opt in option.value:
                if (value := config.getoption(opt)) is None:
                    continue
                if (matcher := matchers.get(option)) is None:
                    matchers[option] = matcher = Matcher()
                add_fn = matcher.add_from_file if opt.endswith("file") else matcher.add
                for v in value.split(";"):
                    if (v := v.strip()):
                        add_fn(v)
        return SelectConfig(  # pylint: disable=E1120
            *tuple(matchers.values()),  # type: ignore[call-arg,arg-type]
            fail_on_missing) if any(matchers.values()) else None

    def get_matchers(self) -> Dict[str, Optional[Matcher]]:
        return {
            k: v
            for k in ("select", "deselect", "skip", "xfail") if (v := getattr(self, k)) is not None
        }


def pytest_addoption(parser: pytest.Parser):
    try:
        pytest_select_version = importlib.metadata.version("pytest-select")
        pytest_skip_version = importlib.metadata.version("pytest-skip")
        raise ValueError(
            f"Conflicting pytest-select {pytest_select_version} and pytest-skip {pytest_skip_version} packages are detected, unistall either one of them"
        )
    except importlib.metadata.PackageNotFoundError:  # noqa: E722
        pass
    select_group = parser.getgroup(
        "select",
        "Modify the list of collected tests.",
    )
    select_group.addoption(
        "--select-from-file",
        action="store",
        dest="selectfromfile",
        default=None,
        help=
        "Select tests given in one or multiple, semicolon-separated, file(s). One line per test name.",
    )
    select_group.addoption(
        "--deselect-from-file",
        action="store",
        dest="deselectfromfile",
        default=None,
        help=
        "Deselect tests given in one or multiple, semicolon-separated, file(s). One line per test name.",
    )
    select_group.addoption(
        "--skip-from-file",
        action="store",
        dest="skipfromfile",
        default=None,
        help="Mark tests from one or multiple, semicolon-separated, file(s) as skipped.",
    )
    select_group.addoption(
        "--xfail-from-file",
        action="store",
        dest="xfailfromfile",
        default=None,
        help="Mark tests from one or multiple, semicolon-separated, file(s) as xfail "
        "(expected to fail).",
    )
    select_group.addoption(
        "--select-test",
        action="store",
        dest="selecttest",
        default=None,
        help="Select one or multiple, semicolon-separated, test names.",
    )
    select_group.addoption(
        "--deselect-test",
        action="store",
        dest="deselecttest",
        default=None,
        help="Deselect one or multiple, semicolon-separated, test names.",
    )
    select_group.addoption(
        "--skip-test",
        action="store",
        dest="skiptest",
        default=None,
        help="Mark one or multiple, semicolon-separated, test names as skipped.",
    )
    select_group.addoption(
        "--xfail-test",
        action="store",
        dest="xfailtest",
        default=None,
        help="Mark one or multiple, semicolon-separated, test names as xfail (expected to fail).",
    )
    select_group.addoption(
        "--select-fail-on-missing",
        action="store_true",
        dest="selectfailonmissing",
        default=False,
        help="Fail instead of warn when not all (de-)selected tests could be found.",
    )
    select_group.addoption(
        "--xfail-strict",
        action="store_true",
        dest="xfailstrict",
        default=False,
        help="Make xfail marks applied via --xfail-from-file/--xfail-test strict, so that an "
        "unexpected pass (XPASS) fails the overall pytest run. By default (this flag unset), "
        "xfail is non-strict, matching pytest's own default: XPASS is reported but does NOT "
        "fail the run or change the exit code.",
    )
    select_group.addoption(
        "--num-shards",
        action="store",
        dest="num_shards",
        default=None,
        help=
        "Specify total num shards to split tests across (must be specified together with --shard-id).",
    )
    select_group.addoption(
        "--shard-id",
        action="store",
        dest="shard_id",
        default=None,
        help="Specify shard id (must be specified together with --num-shards).",
    )
    select_group.addoption(
        "--sharding-mode",
        action="store",
        dest="sharding_mode",
        default="round-robin",
        help=
        "Specify sharding mode for NON-weighted sharding. Available modes: {'contiguous-split', 'round-robin'}",
    )


@pytest.hookimpl(trylast=True)  # pragma: no mutate
def pytest_report_header(config) -> List[str]:  # pylint:disable = R1710
    hdr = []
    for option in SelectOption:
        for opt in option.value:
            if (value := config.getoption(opt)) is None:
                continue
            action = ("selecting" if option == SelectOption.SELECT else
                      "deselecting" if option == SelectOption.DESELECT else
                      "skipping" if option == SelectOption.SKIP else "xfailing")
            value = f"from '{value}'" if opt.endswith("file") else f"'{value}'"
            hdr.append(f"select: {action} tests {value}")
    if config.getoption("selectfailonmissing"):
        hdr.append("select: failing on missing selection items")
    if config.getoption("xfailstrict"):
        hdr.append("select: enforcing strict xfail (XPASS fails the run)")
    return hdr


class SelectPlugin:

    def pytest_collection_modifyitems(  # pylint: disable=R0914
        self,
        session,  # pylint: disable=W0613
        config: pytest.Config,
        items: List[pytest.Item],
    ):
        select_config = SelectConfig.from_config(config)
        sharding_config = ShardingConfig.from_config(config)
        selected: List[pytest.Item]
        deselected: List[pytest.Item]
        skipped: List[pytest.Item]

        if select_config is None:
            if sharding_config is None:
                return
            selected, deselected, skipped = items, [], []
        else:
            selected, deselected, skipped = [], [], []
            select, deselect, skip, xfail = (
                select_config.select,
                select_config.deselect,
                select_config.skip,
                select_config.xfail,
            )
            xfail_strict = config.getoption("xfailstrict")
            for item in items:
                if select is None or select.match_item(item):
                    selected.append(item)
                is_selected = bool(selected) and selected[-1] is item

                # NOTE: `Matcher.match_item()` has the side effect of recording the
                # matched name in `seen_test_names` (used for missing-test detection),
                # independently of whether the corresponding action ends up being
                # applied below. This is intentional: it lets `check_missing_tests()`
                # correctly report "matched a real test" even when a name collision
                # (see xfail handling below) means the action itself isn't applied.
                deselect_matched = deselect is not None and deselect.match_item(item)
                deselect_applied = deselect_matched and is_selected
                if deselect_applied:
                    selected.pop()
                    deselected.append(item)
                    is_selected = False

                skip_matched = skip is not None and skip.match_item(item)
                skip_applied = skip_matched and is_selected
                if skip_applied:
                    selected.pop()
                    skipped.append(item)
                    item.add_marker(pytest.mark.skip(reason="Skipped by pytest-skip"))
                    is_selected = False

                xfail_matched = xfail is not None and xfail.match_item(item)
                if xfail_matched:
                    if is_selected:
                        item.add_marker(
                            pytest.mark.xfail(reason="Xfailed by pytest-skip", strict=xfail_strict))
                    else:
                        # The name also matched --deselect-from-file/--deselect-test or
                        # --skip-from-file/--skip-test (or the test was never selected in
                        # the first place). This is a deliberate precedence decision:
                        # select/deselect/skip win over xfail on a name collision, since
                        # xfail only makes sense for a test whose body actually runs.
                        # Surface the collision explicitly instead of silently dropping
                        # the xfail request with zero signal to the user.
                        reason = ("deselected" if deselect_applied else
                                  "skipped" if skip_applied else "not selected")
                        warnings.warn(
                            UserWarning(
                                f"pytest-skip: '{item.nodeid}' matched --xfail-from-file/"
                                f"--xfail-test, but the test is {reason}; the xfail marker "
                                "was NOT applied. select/deselect/skip take precedence over "
                                "xfail when a test name collides across options."))
            self.select_config = select_config  # pylint: disable=W0201

        if sharding_config is not None:
            selected, deselected = sharding_config.do_sharding(selected, deselected)

        items[:] = skipped + selected
        if deselected:
            config.hook.pytest_deselected(items=deselected)

    def pytest_sessionfinish(self, session, exitstatus):  # pylint: disable=W0613
        if (select_config := getattr(self, "select_config", None)) is not None:
            select_config.check_missing_tests()


class SelectXdistPlugin(SelectPlugin):

    def pytest_testnodedown(self, node, error):  # pylint: disable=W0613
        if (worker_output := getattr(node, "workeroutput", None)) is None:
            return
        if hasattr(self, "select_config"):
            select_config = self.select_config
        else:
            self.select_config = select_config = SelectConfig.from_config(node.config)  # pylint: disable=W0201
        if select_config is None:
            return
        for n, m in select_config.get_matchers().items():
            m.seen_test_names.update(worker_output[f"{n}_seen_test_names"])

    def pytest_sessionfinish(self, session, exitstatus):  # pylint: disable=W0613
        if (workeroutput := getattr(session.config, "workeroutput", None)) is None:
            # Ensure that it runs only in the master process when using xdist:
            super().pytest_sessionfinish(session, exitstatus)
        elif (select_config := getattr(self, "select_config", None)) is not None:
            for n, m in select_config.get_matchers().items():
                workeroutput[f"{n}_seen_test_names"] = m.seen_test_names


def pytest_configure(config: pytest.Config):
    plugin = SelectXdistPlugin() if config.pluginmanager.hasplugin("xdist") else SelectPlugin()
    config.pluginmanager.register(plugin, "pytest_skip")
