"""Launch bundled workers from a trusted package root, independent of cwd."""
from pathlib import Path
import sys

WORKERS = frozenset({'display_watchdog', 'gpu_sensors', 'file_worker', 'drive_health', 'admin_helper'})
BOOTSTRAP = (
    'import runpy,sys; '
    'sys.path.insert(0,sys.argv.pop(1)); '
    'module=sys.argv.pop(1); '
    'sys.argv[0]=module; '
    'runpy.run_module(module,run_name="__main__")'
)


def worker_command(module, *arguments):
    if module not in WORKERS:
        raise ValueError('Unknown worker')
    executable = Path(sys.executable)
    if executable.name.casefold() == 'pythonw.exe':
        executable = executable.with_name('python.exe')
    root = Path(__file__).resolve().parents[1]
    return [str(executable), '-I', '-B', '-c', BOOTSTRAP,
            str(root), 'winpilot.' + module, *(str(v) for v in arguments)]
