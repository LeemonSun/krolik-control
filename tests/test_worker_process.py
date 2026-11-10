import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from winpilot.worker_process import worker_command


class WorkerProcessTests(unittest.TestCase):
    def test_imports_checkout_from_unrelated_directory_in_isolated_mode(self):
        command = worker_command('display_watchdog')
        # Keep production bootstrap and intercept only the final module execution.
        command[4] = (
            'import runpy,json; '
            'runpy.run_module=lambda module,**kw: print(json.dumps('
            '__import__("importlib.util",fromlist=["find_spec"]).find_spec(module).origin)); '
        ) + command[4]
        with tempfile.TemporaryDirectory(prefix='krolik-worker-') as directory:
            result = subprocess.run(command, cwd=directory, capture_output=True,
                                    text=True, timeout=10, check=True)
        self.assertEqual(Path(json.loads(result.stdout)).resolve(),
                         Path(__file__).resolve().parents[1] / 'winpilot/display_watchdog.py')

    def test_arguments_remain_data(self):
        argument = 'folder with spaces;not-a-command.json'
        command = worker_command('file_worker', argument)
        self.assertEqual(command[-1], argument)
        self.assertNotIn(argument, command[4])
        self.assertIn('-I', command)

    def test_only_known_workers(self):
        with self.assertRaises(ValueError):
            worker_command('os')
