import sys
import warnings
from pathlib import Path
from unittest.mock import ANY

import pytest

from prefect._internal.compatibility.deprecated import PrefectDeprecationWarning
from prefect.blocks.core import Block
from prefect.blocks.system import Secret
from prefect.client.orchestration import PrefectClient
from prefect.deployments.steps import run_step
from prefect.deployments.steps.core import StepExecutionError, run_steps
from prefect.deployments.steps.utility import run_shell_script
from prefect.testing.utilities import AsyncMock, MagicMock


@pytest.fixture
async def variables(prefect_client: PrefectClient):
    await prefect_client._client.post(
        "/variables/", json={"name": "test_variable_1", "value": "test_value_1"}
    )
    await prefect_client._client.post(
        "/variables/", json={"name": "test_variable_2", "value": "test_value_2"}
    )


@pytest.fixture(scope="session")
def set_dummy_env_var():
    import os

    os.environ["DUMMY_ENV_VAR"] = "dummy"


class TestRunStep:
    async def test_run_step_runs_importable_functions(self):
        output = await run_step(
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                }
            },
        )
        assert isinstance(output, dict)
        assert output == {
            "stdout": "this is a test",
            "stderr": "",
        }

    async def test_run_step_errors_with_improper_format(self):
        with pytest.raises(ValueError, match="unexpected"):
            await run_step(
                {
                    "prefect.deployments.steps.run_shell_script": {
                        "script": "echo 'this is a test'"
                    },
                    "jedi": 0,
                }
            )

    async def test_run_step_resolves_block_document_references_before_running(self):
        await Secret(value="echo 'I am a secret!'").save(name="test-secret")

        output = await run_step(
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "{{ prefect.blocks.secret.test-secret }}",
                }
            }
        )
        assert isinstance(output, dict)
        assert output == {
            "stdout": "I am a secret!",
            "stderr": "",
        }

    async def test_run_step_resolves_environment_variables_before_running(
        self, monkeypatch
    ):
        monkeypatch.setenv("TEST_ENV_VAR", "test_value")
        output = await run_step(
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": 'echo "{{ $TEST_ENV_VAR }}"',
                }
            }
        )
        assert isinstance(output, dict)
        assert output == {
            "stdout": "test_value",
            "stderr": "",
        }

    async def test_run_step_resolves_variables_before_running(self, variables):
        output = await run_step(
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": (
                        "echo '{{ prefect.variables.test_variable_1 }}:{{"
                        " prefect.variables.test_variable_2 }}'"
                    ),
                }
            }
        )
        assert isinstance(output, dict)
        assert output == {
            "stdout": "test_value_1:test_value_2",
            "stderr": "",
        }

    async def test_run_step_runs_async_functions(self):
        output = await run_step(
            {
                "anyio.run_process": {
                    "command": ["echo", "hello world"],
                }
            }
        )
        assert output.returncode == 0
        assert output.stdout.decode().strip() == "hello world"


class TestRunSteps:
    async def test_run_steps_runs_multiple_steps(self):
        steps = [
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                    "id": "why_not_to_panic",
                }
            },
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": r"echo Don\'t Panic: {{ why_not_to_panic.stdout }}"
                }
            },
        ]
        step_outputs = await run_steps(steps, {})
        assert step_outputs == {
            "why_not_to_panic": {
                "stdout": "this is a test",
                "stderr": "",
            },
            "stdout": "Don't Panic: this is a test",
            "stderr": "",
        }

    async def test_run_steps_handles_error_gracefully(self, variables):
        steps = [
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                    "id": "why_not_to_panic",
                }
            },
            {
                "nonexistent.module": {
                    "__fn": lambda x: x * 2,
                    "value": "{{ step_output_1 }}",
                }
            },
        ]
        with pytest.raises(StepExecutionError, match="nonexistent.module"):
            await run_steps(steps, {})

    async def test_run_steps_prints_step_names(
        self,
    ):
        mock_print = MagicMock()
        steps = [
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                    "id": "why_not_to_panic",
                }
            },
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": (
                        'bash -c echo "Don\'t Panic: {{ why_not_to_panic.stdout }}"'
                    )
                }
            },
        ]
        await run_steps(steps, {}, print_function=mock_print)
        mock_print.assert_any_call(" > Running run_shell_script step...")

    async def test_run_steps_prints_deprecation_warnings(self, monkeypatch):
        def func(*args, **kwargs):
            warnings.warn("this is a warning", DeprecationWarning)
            return {}

        monkeypatch.setattr("prefect.deployments.steps.run_shell_script", func)

        mock_print = MagicMock()
        steps = [
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                    "id": "why_not_to_panic",
                }
            },
        ]
        await run_steps(steps, {}, print_function=mock_print)
        mock_print.assert_any_call("this is a warning", style="yellow")

    async def test_run_steps_prints_prefect_deprecation_warnings(self, monkeypatch):
        def func(*args, **kwargs):
            warnings.warn("this is a warning", PrefectDeprecationWarning)
            return {}

        monkeypatch.setattr("prefect.deployments.steps.run_shell_script", func)

        mock_print = MagicMock()
        steps = [
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                    "id": "why_not_to_panic",
                }
            },
        ]
        await run_steps(steps, {}, print_function=mock_print)
        mock_print.assert_any_call("this is a warning", style="yellow")

    async def test_run_steps_can_print_warnings_without_style(self, monkeypatch):
        def func(*args, **kwargs):
            warnings.warn("this is a warning", PrefectDeprecationWarning)
            return {}

        monkeypatch.setattr("prefect.deployments.steps.run_shell_script", func)

        # raise an exception when style is passed. exception type is irrelevant
        mock_print = MagicMock(
            side_effect=lambda *args, **kwargs: 1 / 0 if kwargs.get("style") else None
        )
        steps = [
            {
                "prefect.deployments.steps.run_shell_script": {
                    "script": "echo 'this is a test'",
                    "id": "why_not_to_panic",
                }
            },
        ]
        await run_steps(steps, {}, print_function=mock_print)
        mock_print.assert_any_call("this is a warning")


class MockCredentials:
    def __init__(self, token: str, username: str = None, password: str = None):
        self.token = token
        self.username = username
        self.password = password

        self.data = {
            "value": {
                "token": self.token,
                "username": self.username,
                "password": self.password,
            }
        }

    async def save(self, name: str):
        pass

    async def load(self, name: str):
        return MockCredentials(token="mock-token")


@pytest.fixture
def git_repository_mock(monkeypatch):
    git_repository_mock = MagicMock()
    pull_code_mock = AsyncMock()
    git_repository_mock.return_value.pull_code = pull_code_mock
    git_repository_mock.return_value.destination = Path.cwd() / "repo"
    monkeypatch.setattr(
        "prefect.deployments.steps.pull.GitRepository",
        git_repository_mock,
    )
    return git_repository_mock


class TestGitCloneStep:
    async def test_git_clone(self, git_repository_mock):
        output = await run_step(
            {
                "prefect.deployments.steps.git_clone": {
                    "repository": "https://github.com/org/repo.git",
                }
            }
        )
        assert output["directory"] == "repo"
        git_repository_mock.assert_called_once_with(
            url="https://github.com/org/repo.git",
            credentials=None,
            branch=None,
            include_submodules=False,
        )
        git_repository_mock.return_value.pull_code.assert_awaited_once()

    async def test_deprecated_git_clone_project(self, git_repository_mock):
        with pytest.warns(DeprecationWarning):
            output = await run_step(
                {
                    "prefect.projects.steps.git_clone_project": {
                        "repository": "https://github.com/org/repo.git",
                    }
                }
            )
        assert output["directory"] == "repo"
        git_repository_mock.assert_called_once_with(
            url="https://github.com/org/repo.git",
            credentials=None,
            branch=None,
            include_submodules=False,
        )
        git_repository_mock.return_value.pull_code.assert_awaited_once()

    async def test_git_clone_include_submodules(self, git_repository_mock):
        output = await run_step(
            {
                "prefect.deployments.steps.git_clone": {
                    "repository": "https://github.com/org/has-submodules.git",
                    "include_submodules": True,
                }
            }
        )
        assert output["directory"] == "repo"
        git_repository_mock.assert_called_once_with(
            url="https://github.com/org/has-submodules.git",
            credentials=None,
            branch=None,
            include_submodules=True,
        )
        git_repository_mock.return_value.pull_code.assert_awaited_once()

    async def test_git_clone_with_access_token(self, git_repository_mock):
        await Secret(value="my-access-token").save(name="my-access-token")
        await run_step(
            {
                "prefect.deployments.steps.git_clone": {
                    "repository": "https://github.com/org/repo.git",
                    "access_token": "{{ prefect.blocks.secret.my-access-token }}",
                }
            }
        )
        git_repository_mock.assert_called_once_with(
            url="https://github.com/org/repo.git",
            credentials={"access_token": "my-access-token"},
            branch=None,
            include_submodules=False,
        )
        git_repository_mock.return_value.pull_code.assert_awaited_once()

    async def test_git_clone_with_credentials(self, git_repository_mock):
        class MockGitCredentials(Block):
            username: str
            password: str

        await MockGitCredentials(username="marvin42", password="hunter2").save(
            name="my-credentials"
        )
        await run_step(
            {
                "prefect.deployments.steps.git_clone": {
                    "repository": "https://github.com/org/repo.git",
                    "credentials": (
                        "{{ prefect.blocks.mockgitcredentials.my-credentials }}"
                    ),
                }
            }
        )
        git_repository_mock.assert_called_once_with(
            url="https://github.com/org/repo.git",
            credentials={"username": "marvin42", "password": "hunter2"},
            branch=None,
            include_submodules=False,
        )
        git_repository_mock.return_value.pull_code.assert_awaited_once()


class TestRunShellScript:
    async def test_run_shell_script_single_command(self, capsys):
        result = await run_shell_script("echo Hello World", stream_output=True)
        assert result["stdout"] == "Hello World"
        assert result["stderr"] == ""

        # Validate the output was streamed to the console
        out, err = capsys.readouterr()
        assert out.strip() == "Hello World"
        assert err == ""

    async def test_run_shell_script_multiple_commands(self, capsys):
        script = """
        echo First Line
        echo Second Line
        """
        result = await run_shell_script(script, stream_output=True)
        assert result["stdout"] == "First Line\nSecond Line"
        assert result["stderr"] == ""

        # Validate the output was streamed to the console
        out, err = capsys.readouterr()
        assert out.strip() == "First Line\nSecond Line"
        assert err == ""

    @pytest.mark.skipif(
        sys.platform == "win32", reason="stderr redirect does not work on Windows"
    )
    async def test_run_shell_script_stderr(self, capsys):
        script = "bash -c '>&2 echo Error Message'"
        result = await run_shell_script(script, stream_output=True)
        assert result["stdout"] == ""
        assert result["stderr"] == "Error Message"

        # Validate the error was streamed to the console
        out, err = capsys.readouterr()
        assert out == ""
        assert err.strip() == "Error Message"

    @pytest.mark.parametrize(
        "script,expected",
        [
            ("bash -c 'echo $TEST_ENV_VAR'", "Test Value"),
            ("echo $TEST_ENV_VAR", "$TEST_ENV_VAR"),
        ],
    )
    async def test_run_shell_script_with_env(self, script, expected, capsys):
        result = await run_shell_script(
            script, env={"TEST_ENV_VAR": "Test Value"}, stream_output=True
        )
        assert result["stdout"] == expected
        assert result["stderr"] == ""

        # Validate the output was streamed to the console
        out, err = capsys.readouterr()
        assert out.strip() == expected
        assert err == ""

    @pytest.mark.parametrize(
        "script",
        [
            "echo $DUMMY_ENV_VAR",
            "bash -c 'echo $DUMMY_ENV_VAR'",
        ],
    )
    async def test_run_shell_script_expand_env(self, script, capsys, set_dummy_env_var):
        result = await run_shell_script(
            script,
            expand_env_vars=True,
            stream_output=True,
        )

        assert result["stdout"] == "dummy"
        assert result["stderr"] == ""

    async def test_run_shell_script_no_expand_env(self, capsys, set_dummy_env_var):
        result = await run_shell_script(
            "echo $DUMMY_ENV_VAR",
            stream_output=True,
        )

        assert result["stdout"] == "$DUMMY_ENV_VAR"
        assert result["stderr"] == ""

    async def test_run_shell_script_no_output(self, capsys):
        result = await run_shell_script("echo Hello World", stream_output=False)
        assert result["stdout"] == "Hello World"
        assert result["stderr"] == ""

        # Validate nothing was streamed to the console
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    async def test_run_shell_script_in_directory(self):
        parent_dir = str(Path.cwd().parent)
        result = await run_shell_script(
            "pwd", directory=parent_dir, stream_output=False
        )
        assert result["stdout"] == parent_dir
        assert result["stderr"] == ""

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="_open_anyio_process errors when mocking OS in test context",
    )
    async def test_run_shell_script_split_on_windows(self, monkeypatch):
        # return type needs to be mocked to avoid TypeError
        shex_split_mock = MagicMock(return_value=["echo", "Hello", "World"])
        monkeypatch.setattr(
            "prefect.deployments.steps.utility.shlex.split",
            shex_split_mock,
        )
        result = await run_shell_script("echo Hello World")
        # validates that command is parsed as non-posix
        shex_split_mock.assert_called_once_with("echo Hello World", posix=False)
        assert result["stdout"] == "Hello World"
        assert result["stderr"] == ""


class MockProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def wait(self):
        pass


class TestPipInstallRequirements:
    async def test_pip_install_reqs_runs_expected_command(self, monkeypatch):
        open_process_mock = MagicMock(return_value=MockProcess(0))
        monkeypatch.setattr(
            "prefect.deployments.steps.utility.open_process",
            open_process_mock,
        )

        mock_stream_capture = AsyncMock()

        monkeypatch.setattr(
            "prefect.deployments.steps.utility._stream_capture_process_output",
            mock_stream_capture,
        )

        await run_step(
            {
                "prefect.deployments.steps.pip_install_requirements": {
                    "id": "pip-install-step"
                }
            }
        )

        open_process_mock.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=None,
            stderr=ANY,
            stdout=ANY,
        )

    async def test_pip_install_reqs_custom_requirements_file(self, monkeypatch):
        open_process_mock = MagicMock(return_value=MockProcess(0))
        monkeypatch.setattr(
            "prefect.deployments.steps.utility.open_process",
            open_process_mock,
        )

        mock_stream_capture = AsyncMock()

        monkeypatch.setattr(
            "prefect.deployments.steps.utility._stream_capture_process_output",
            mock_stream_capture,
        )

        await run_step(
            {
                "prefect.deployments.steps.pip_install_requirements": {
                    "id": "pip-install-step",
                    "requirements_file": "dev-requirements.txt",
                }
            }
        )

        open_process_mock.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "-r", "dev-requirements.txt"],
            cwd=None,
            stderr=ANY,
            stdout=ANY,
        )

    async def test_pip_install_reqs_with_directory_step_output_succeeds(
        self, monkeypatch
    ):
        open_process_mock = MagicMock(return_value=MockProcess(0))
        monkeypatch.setattr(
            "prefect.deployments.steps.utility.open_process",
            open_process_mock,
        )

        mock_stream_capture = AsyncMock()

        monkeypatch.setattr(
            "prefect.deployments.steps.utility._stream_capture_process_output",
            mock_stream_capture,
        )

        steps = [
            {
                "prefect.deployments.steps.git_clone": {
                    "id": "clone-step",
                    "repository": "https://github.com/PrefectHQ/hello-projects.git",
                }
            },
            {
                "prefect.deployments.steps.pip_install_requirements": {
                    "id": "pip-install-step",
                    "directory": "{{ clone-step.directory }}",
                    "requirements_file": "requirements.txt",
                }
            },
        ]

        step_outputs = {
            "clone-step": {"directory": "hello-projects"},
            "directory": "hello-projects",
            "pip-install-step": {"stdout": "", "stderr": ""},
            "stdout": "",
            "stderr": "",
        }

        open_process_mock.run.return_value = MagicMock(**step_outputs)

        output = await run_steps(steps)

        assert output == step_outputs

        open_process_mock.assert_called_once_with(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                "requirements.txt",
            ],
            cwd="hello-projects",
            stderr=ANY,
            stdout=ANY,
        )

    async def test_pip_install_fails_on_error(self):
        with pytest.raises(RuntimeError) as exc:
            await run_step(
                {
                    "prefect.deployments.steps.pip_install_requirements": {
                        "id": "pip-install-step",
                        "requirements_file": "doesnt-exist.txt",
                    }
                }
            )
        assert (
            "pip_install_requirements failed with error code 1: ERROR: Could not open "
            "requirements file: [Errno 2] No such file or directory: "
            "'doesnt-exist.txt'"
            in str(exc.value)
        )
