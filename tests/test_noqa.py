import blark.transform as tf

from catscan.lint import lint_check, ErrorInfo
from support import make_settings, tcpou, function_block, method, get_errors


def test_no_noqa(tmp_path):
    settings = make_settings()

    @lint_check("TST001")
    def test_lint_check(stat: tf.BinaryOperation):
        if stat.op == "+":
            yield ErrorInfo(
                message="I don't like addition!",
                violating=stat,
            )

    example = tcpou(
        function_block(
            method(
                decl="""
                    VAR
                        s_nTest : INT := 0;
                    END_VAR
                """,
                implementation="""
                    s_nTest := s_nTest + 1;
                """
            )
        )
    )

    errors = list(get_errors(example, tmp_path, settings))
    assert len(errors) == 1
    assert errors[0].message == "I don't like addition!"
    assert errors[0].loc.error_line().strip() == "s_nTest := s_nTest + 1;"


def test_noqa(tmp_path):
    settings = make_settings()

    @lint_check("TST001")
    def test_lint_check(stat: tf.BinaryOperation):
        if stat.op == "+":
            yield ErrorInfo(
                message="I don't like addition!",
                violating=stat,
            )

    example = tcpou(
        function_block(
            method(
                decl="""
                    VAR
                        s_nTest : INT := 0;
                    END_VAR
                """,
                implementation="""
                    s_nTest := s_nTest + 1;  // noqa: TST001
                """
            )
        )
    )

    for error in get_errors(example, tmp_path, settings):
        # expect no errors
        raise Exception(error.message)
