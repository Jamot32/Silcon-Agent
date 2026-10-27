"""Fast source-only checks; not a simulator or timing qualification."""
import ast
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parent
for path in (ROOT / "sa_clock.py", ROOT / "test_clock.py", ROOT / "qualify.py"):
    ast.parse(path.read_text(), filename=str(path))

# Evaluate only check_value with synthetic stand-ins; no cocotb or EDA is run.
module = ast.parse((ROOT / "sa_clock.py").read_text())
function = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                and node.name == "check_value")
code = compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "sa_clock.py"), "exec")
namespace = {}
exec(code, namespace)
check_value = namespace["check_value"]


class NoRead:
    @property
    def value(self):
        raise AssertionError("masked signal was read")


class Unknown:
    value = types.SimpleNamespace(is_resolvable=False)


class Known:
    class Value:
        is_resolvable = True

        def __int__(self):
            return 3

    value = Value()


check_value(NoRead(), None, "masked")
check_value(Known(), 3, "known")
for signal, expected in ((Unknown(), 0), (Known(), 2)):
    try:
        check_value(signal, expected, "negative control")
    except AssertionError:
        pass
    else:
        raise AssertionError("negative control passed")
print("offline source checks passed; simulator not run")
