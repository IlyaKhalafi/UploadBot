from unittest.mock import Mock

import pytest

from uploadbot.app import main
from uploadbot.config import Settings


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_information_commands_need_no_credentials(flag, monkeypatch, capsys):
    settings = Mock(side_effect=AssertionError("Credentials should not be read"))
    monkeypatch.setattr(Settings, "from_env", settings)
    with pytest.raises(SystemExit) as result:
        main([flag])
    assert result.value.code == 0
    assert "uploadbot" in capsys.readouterr().out
    settings.assert_not_called()


def test_configuration_check_does_not_connect(monkeypatch, capsys):
    monkeypatch.setattr(Settings, "from_env", lambda: Settings(123, "a" * 32, "123:test"))
    runner = Mock(side_effect=AssertionError("Network should not be used"))
    monkeypatch.setattr("uploadbot.app.run", runner)
    main(["--check-config"])
    assert "Configuration is valid." in capsys.readouterr().out
    runner.assert_not_called()
