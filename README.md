# CATScan

A linter for TwinCAT code, based on [blark](https://github.com/High-Voltage-Engineering/blark).

## Example Usage

Run the catscan module with glob patterns for the source files to include:
```commandline
catscan -s /path/to/catscan.yaml -e **/FBG_* -e **/Generated/**.* -p **/*.TcDUT -p **/*.TcGVL -p **/*.TcIO -p **/*.TcPOU
```

## Loading Plugins

You can load plugins from python modules. To do this, first implement your check as follows:

```python
""" /path/to/catscan_plugin.py """
from catscan.lint import lint_check, ErrorInfo
from catscan.utils import tc3

from blark.summary import MethodSummary


# Checks must have a code consisting of 2-4 capital letters and 3-4 numbers.
# They must be unique among lint checks. The check signature must have a 
# catscan.lint.base.CheckableObject as first argument, which is one of:
# - A blark.transform statement (sub)type
# - A blark.transform Expression (sub)type
# - A blark.summary Summary (sub)type
# Additionally, an argument ctx: catscan.lint.context.Context may be passed, 
# containing information about the current context and a blark.summary.CodeSummary
# with all context for the parsed files. Also a settings: catscan.Settings object 
# may be passed, containing global settings and per-check settings.
@lint_check("CHK001")
def my_lint_check(meth: MethodSummary):
    """Check whether test method is left in program"""
    # ^doc string is used as check description in catscan list
    if tc3.streq(meth.name, "_test_method"):
      
        # Errors are yielded as ErrorInfo objects, containing a message, but also 
        # a violating object (in the case of a statement, expression or declaration)
        yield ErrorInfo(
            message="Test method is left in program",
        )

...
```
The plugin is loaded if it is passed to `catscan` as
```commandline
catscan --plugin /path/to/catscan_plugin.py lint ...
```
which then loads your plugin module and registers the check.

### Implemented Checks

- `ARG001`  `function_call_named_args`:
  Checks whether a function call with at least a configured amount of parameters uses
  named arguments, as to prevent mistakes in (compatible) argument order.
- `FUNC001` `function_exists`:
  Check if all called functions exist, and have the right capitalization.
- `FUNC100` `super_call_only_current_method`:
  Check if a SUPER^.<method>() call ONLY happens from <method> itself.
- `EXP001`  `unsigned_underflow`:
  Detect possible unsigned underflows in the code. This is a common cause for buffer
  overruns when (accidentally) done in for loop bounds.
- `EXP002`  `division_by_zero`:
  Detect potential divisions by zero in the code.
- `FUNC101` `super_call_when_possible`:
  Checks that a SUPER^.<method>() call is always present in a method if possible,
  though it may occur on some optional code path.
- `RET001`  `method_has_return`:
  Check if method has return statement (assignment to method name)
- `RET002`  `method_returns_all_out_vars`:
  Check if method assigns to all output variables
- `RET101`  `property_has_return`:
  Check if property getter has return statement (assignment to property name)
- `FUNC102` `super_call_in_function_block`:
  Check whether SUPER^() is called from a function block body (with extensions)
- `PROP001` `prop_setter_reads_set_value`:
  Check whether the property setter value is actually read.
- `PROP002` `prop_setter_value_not_written_to`:
  Check whether the property setter value is never written to.
- `STAT001` `case_statement_cases`:
  Check whether all enum values are present in a case statement (or an else statement
  must be present)
- `VAR000`  `invalid_scoping`:
  Check if variable can be found in the context. If not, this actually more likely
  points to an error in the linter itself. Also checks if THIS / SUPER / invalid method
  returns are used.
- `VAR001`  `variable_existence_and_capitalization`:
  Validate that variables are capitalized properly (or even exist at all)
- `VAR002`  `declaration_naming_convention`:
  Check if variable declarations adhere to our naming standards
- `VAR100`  `uninitialized_var_read`:
  Check whether uninitialized variables are read before they are written.
