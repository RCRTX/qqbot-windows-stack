"""Regression tests for config preservation and instance ownership boundaries."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseToolsTests(unittest.TestCase):
    def test_setup_check_and_existing_config_preservation(self):
        setup = load("setup")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / "template.json"
            example.write_text('{"enabled": false}', encoding="utf-8")
            with patch.object(setup, "ROOT", root), patch.object(setup, "JOBS", [("template.json", "config.json")]):
                with patch.object(sys, "argv", ["setup.py", "--check"]), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(setup.main(), 0)
                self.assertFalse((root / "config.json").exists())
                with patch.object(sys, "argv", ["setup.py"]), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(setup.main(), 0)
                    target = root / "config.json"
                    target.write_text('{"custom": 42}', encoding="utf-8")
                    self.assertEqual(setup.main(), 0)
                self.assertEqual(json.loads(target.read_text()), {"custom": 42})

    def test_preflight_refuses_foreign_port_before_creating_logs(self):
        stack = load("stack")
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            root = Path(directory)
            service = {"port": listener.getsockname()[1], "logs": root / "logs"}
            with patch.object(stack, "SERVICES", {"monitor": service}), patch.object(stack, "process_module"), patch.object(stack, "owned_process", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "occupied"):
                    stack.preflight(["monitor"])
            self.assertFalse((root / "logs").exists())

    def test_stop_does_nothing_without_verified_process(self):
        stack = load("stack")
        with patch.object(stack, "process_module") as process_module, patch.object(stack, "owned_process", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            stack.stop("monitor")
            process_module.return_value.wait_procs.assert_not_called()

    def test_local_proxy_bypass_appends_existing_entries(self):
        stack = load("stack")
        with patch.object(stack.os, "environ", {"NO_PROXY": "example.org", "no_proxy": "internal"}):
            env = stack.environment()
        self.assertIn("example.org", env["NO_PROXY"])
        self.assertIn("internal", env["no_proxy"])
        self.assertIn("127.0.0.1", env["NO_PROXY"])
        self.assertEqual(env["QQBOT_SNOWLUMA_WATCHDOG"], "0")

    def test_panel_stop_preserves_stop_worker_and_stops_panel_last(self):
        stack = load("stack")
        service = Mock(pid=100)
        worker = Mock(pid=200)
        worker_child = Mock(pid=201)
        bot_child = Mock(pid=300)
        worker.children.return_value = [worker_child]
        service.children.return_value = [worker, worker_child, bot_child]
        bot_child.exe.return_value = str(ROOT / ".venv/Scripts/python.exe")
        bot_child.cwd.return_value = str(ROOT)
        psutil = SimpleNamespace(Process=Mock(return_value=worker), Error=Exception,
                                 NoSuchProcess=ProcessLookupError,
                                 wait_procs=Mock(return_value=([], [])))
        with tempfile.TemporaryDirectory() as directory, patch.object(stack, "process_module", return_value=psutil), patch.object(stack, "owned_process", return_value=service), patch.object(stack.os, "getpid", return_value=200), patch.object(stack, "state_file", return_value=Path(directory) / "pid.json"), contextlib.redirect_stdout(io.StringIO()):
            stack.stop("panel")
        service.terminate.assert_called_once()
        bot_child.terminate.assert_called_once()
        worker.terminate.assert_not_called()
        worker_child.terminate.assert_not_called()
        with patch.object(stack, "stop") as stop, patch.object(sys, "argv", ["stack.py", "stop"]):
            self.assertEqual(stack.main(), 0)
        self.assertEqual([call.args[0] for call in stop.call_args_list], ["bot", "monitor", "panel"])


if __name__ == "__main__":
    unittest.main()
