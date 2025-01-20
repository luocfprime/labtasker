import pytest


@pytest.mark.unit
class TestSanitizeSensitiveTraceback:
    """
    install_traceback_filter() is installed in labtasker.__init__.py
    """

    def test_sanitize_simple_password_in_traceback(self, capsys):
        def example_function():
            password = "supersecretpassword"
            raise ValueError(f"Error with password={password}")

        with pytest.raises(ValueError):
            example_function()

        captured = capsys.readouterr()
        assert (
            "password=supersecretpassword" not in captured.out
        ), f"captured: {captured}"

    def test_sanitize_password_in_dict_format(self, capsys):
        def example_function():
            raise ValueError(f"Data: {{'username': 'user1', 'password': 'mypassword'}}")

        with pytest.raises(ValueError):
            example_function()

        captured = capsys.readouterr()
        assert "mypassword" not in captured.out

    def test_no_password_in_traceback(self, capsys):
        def example_function():
            raise ValueError("An error occurred with no sensitive data")

        with pytest.raises(ValueError):
            example_function()

        captured = capsys.readouterr()
        assert "*****" not in captured.out
