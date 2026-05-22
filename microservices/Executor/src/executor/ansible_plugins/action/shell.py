import shlex
import subprocess
import threading

try:
    from ansible.plugins.action.shell import ActionModule as _BuiltinShell
except ImportError:
    from ansible.plugins.action.command import ActionModule as _BuiltinShell

from ansible.utils.display import Display

display = Display()


def _exec(container, cmd):
    proc = subprocess.run(
        ['docker', 'exec', container, '/bin/sh', '-c', cmd],
        capture_output=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _stream_exec(container, cmd, stdin_data=None):
    proc = subprocess.Popen(
        ['docker', 'exec', '-i', container, '/bin/sh', '-c', cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
    )

    if stdin_data:
        proc.stdin.write(stdin_data.encode())
        proc.stdin.close()

    stdout_chunks = []
    stderr_chunks = []

    def drain_stderr():
        stderr_chunks.extend(proc.stderr)

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    for line in proc.stdout:
        display.display(line.decode('utf-8', 'replace').rstrip())
        stdout_chunks.append(line)

    t.join()
    proc.wait()

    return (
        proc.returncode,
        b''.join(stdout_chunks).decode('utf-8', 'replace'),
        b''.join(stderr_chunks).decode('utf-8', 'replace'),
    )

DOCKER_TRANSPORTS = ('docker', 'community.docker.docker')


class ActionModule(_BuiltinShell):

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = {}

        if self._connection.transport not in DOCKER_TRANSPORTS:
            return super().run(tmp, task_vars)

        result = super(_BuiltinShell, self).run(tmp, task_vars)

        cmd = (
            self._task.args.get('_raw_params', '')
            or self._task.args.get('cmd', '')
        ).strip()

        chdir = self._task.args.get('chdir')
        stdin_data = self._task.args.get('stdin')
        creates = self._task.args.get('creates')
        removes = self._task.args.get('removes')

        container = task_vars.get('ansible_host', task_vars.get('inventory_hostname', ''))

        if creates:
            rc, _, _ = _exec(container, f'test -e {shlex.quote(creates)}')
            if rc == 0:
                result.update(changed=False, skipped=True, msg=f'skipped: {creates} exists')
                return result

        if removes:
            rc, _, _ = _exec(container, f'test -e {shlex.quote(removes)}')
            if rc != 0:
                result.update(changed=False, skipped=True, msg=f'skipped: {removes} not found')
                return result

        if chdir:
            cmd = f'cd {shlex.quote(chdir)} && {cmd}'

        rc, stdout, stderr = _stream_exec(container, cmd, stdin_data)

        result.update(
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            stdout_lines=stdout.splitlines(),
            stderr_lines=stderr.splitlines(),
            changed=True,
            failed=rc != 0,
            msg='non-zero return code' if rc != 0 else '',
        )
        return result
