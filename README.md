pytest-skip
=============

This is a [pytest](https://pytest.org) plugin which allows to (de-)select or skip tests by name from a list loaded from a file.

pytest-skip expands upon the capabilities of the original [pytest-select](https://github.com/ulope/pytest-select) plugin
by adding
- `--skip-from-file` option to skip tests instead of deselecting
- `--xfail-from-file` option to mark tests as expected to fail (xfail) instead of deselecting or skipping
- support to (de-)select, skip or xfail parametrized tests without needing to specify test instance qualifiers
- support for blank and comment lines in the selection files
- better integration with the `pytest-xdist`, plugin warning and error messages are passed to the master node with proper stdout or stderr outputs
- sharding functionality to distribute tests across several nodes
- an ability to select/skip parameters combinations matching a certain regular expression.
Put your regexp in the square brackets as a raw string and end the line with `@regexp` suffix:
`file.py::test[r"REGEXP"]@regexp`


Usage
-----

This plugin adds new command line options to pytest:

- ``--select-from-file``
- ``--deselect-from-file``
- ``--skip-from-file``
- ``--xfail-from-file``
- ``--select-test``
- ``--deselect-test``
- ``--skip-from-test``
- ``--xfail-test``
- ``--select-fail-on-missing``
- ``--xfail-strict``
- ``--num-shards``, ``--shard-id`` and ``--sharding-mode``

The first four expect an argument that resolves to one or multiple, semicolon-separated, UTF-8 encoded text file(s)
containing one test name per line. Text file may contain blank and comment lines (starts from `#`). All four
(select, deselect, skip, xfail) options can be used simultaneously.

The next four expect one or multiple, semicolon-separated, test names to be selected, deselected, skipped or marked xfail.

The next one changes the behaviour in case (de-)selected, skipped or xfailed test names are missing from the to-be executed tests.
By default a warning is emitted and the remaining selected tests are executed as normal.
By using the ``--select-fail-on-missing`` flag this behaviour can be changed to instead abort execution in that case.

``--skip-from-file``/``--skip-test`` and ``--xfail-from-file``/``--xfail-test`` differ in an important way: a skipped
test's body never runs, while an xfailed test's body does run and is simply expected to fail. If an xfailed test
unexpectedly passes, it is reported as ``XPASS`` rather than a plain pass, which is useful to surface tests that were
expected to fail but no longer do.

**Important**: by default, an ``XPASS`` does **not** fail the overall pytest run or change its exit code — this
matches pytest's own default (non-strict) ``xfail`` behaviour. In other words, ``--xfail-from-file``/``--xfail-test``
alone will surface a regression-fix in the ``XPASS`` line of the output, but it will **not** turn a CI run red on
its own. If you want an unexpected pass to actually fail the run (and the exit code), either pass ``--xfail-strict``
on the command line, or set ``xfail_strict = true`` in your own project's pytest configuration (which applies to
all xfail markers, not just the ones added by this plugin).

If a test name is listed in **both** ``--xfail-from-file``/``--xfail-test`` **and**
``--skip-from-file``/``--skip-test`` or ``--deselect-from-file``/``--deselect-test``, the skip/deselect option takes
precedence: the test is skipped or deselected as usual, and the xfail marker is **not** applied to it (marking a
test that never runs as xfail would be meaningless). This is not a silent no-op: pytest-skip emits a warning naming
the colliding test so the conflict isn't hidden.

The sharding parameters allow users to split the test sets into even portions across multiple shards for parallel execution.
The tests that are filtered out for a shard will be deselected.

Test names are expected in the same format as seen in the output of
``pytest --collect-only --quiet`` for example.

Both plain test names or complete node ids (e.g. ``test_file.py::test_name``) are accepted.

Example::

    $~ cat select.txt
    test_something
    test_parametrized[1]
    test_parametrized
    tests/test_foo.py::test_other
    test_parametrized_complex[r"[8|16]-.*-.*"]@regexp
    tests/test_foo.py::test_params[r"int32-.*-.*"]@regexp

    $~ cat deselect.txt
    tests/test_foo.py::test_params[r"bf32-.*-.*"]@regexp

    $~ cat skip1.txt
    test_parametrized[1]
    test_parametrized[2]

    $~ cat skip2.txt
    test_parametrized[r"[579]"]@regexp

    $~ cat xfail.txt
    test_parametrized[3]
    test_parametrized_complex[r"32-.*-.*"]@regexp

    $~ pytest --select-from-file select.txt
    $~ pytest --deselect-from-file deselect.txt
    $~ pytest --select-from-file select.txt --deselect-from-file deselect.txt --skip-from-file skip1.txt:skip2.txt
    $~ pytest --skip-from-file skip1.txt:skip2.txt --num-shards=4 --shard-id=0 --sharding-mode=round-robin
    $~ pytest --skip-from-file skip1.txt:skip2.txt --num-shards=4 --shard-id=0 --sharding-mode=contiguous-split
    $~ pytest --xfail-from-file xfail.txt
    $~ pytest --xfail-test "test_parametrized[3];test_parametrized[4]"
    $~ pytest --xfail-from-file xfail.txt --xfail-strict


Install from source
-------------------

```bash
git clone --recursive https://github.com/vlad-penkin/pytest-skip
# Run this command from the pytest-skip directory after cloning the source code using the command above
pip install .
```

Install in development mode
---------------------------

To install plugin in development mode run::

```bash
pip install -e .
```

Questions
---------

Why not use pytest's builtin ``-k`` option
******************************************

The ``-k`` selection mechanism is (currently) unable to deal with selecting multiple parametrized
tests and is also a bit fragile since it matches more than just the test name.
Additionally, depending on the number of tests, giving test names on the command line can overflow
the maximum command length.

Version History
---------------
- ``v0.3.0`` (unreleased):
    - Added `--xfail-from-file` and `--xfail-test` options to mark tests as expected to fail (xfail) instead of
      deselecting or skipping them. Unlike skip, an xfailed test's body still runs; an unexpected pass is reported
      as `XPASS`. By default this does NOT fail the run (matching pytest's own non-strict xfail default); use the
      new `--xfail-strict` option (or your project's `xfail_strict = true` config) if you want an unexpected pass
      to fail the run.
    - Added `--xfail-strict` option to make xfail marks applied by this plugin strict.
    - When a test name collides between `--xfail-from-file`/`--xfail-test` and
      `--skip-from-file`/`--skip-test`/`--deselect-from-file`/`--deselect-test`, skip/deselect now deliberately take
      precedence and the xfail marker is not applied; a warning is emitted naming the collision instead of silently
      dropping the xfail request.

- ``v0.2.0`` - 9/12/2025:
    - Added sharding functionality (`--num-shards`, `--shard-id`, `--sharding-mode`) to distribute tests across multiple nodes
    - Added ability to (de-)select or skip tests directly by name (`--select-test`, `--deselect-test`, `--skip-test`)
    - Extended `--*-from-file` options to accept multiple, semicolon-separated files simultaneously
    - Introduced support for selecting/skipping parameter combinations with regular expressions using the `@regexp` syntax
    - Improved integration of simultaneous use of `--select-from-file`, `--deselect-from-file`, and `--skip-from-file`

- ``v0.1.0`` - 4/4/2025:
    - Initial release
