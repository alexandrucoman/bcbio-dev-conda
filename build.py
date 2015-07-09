"""Update conda packages on binstars with latest versions"""
import os
import six
import subprocess
import time

ATTEMPTS = 3
RETRY_INTERVAL = 0.1


def execute(command, **kwargs):
    """Helper method to shell out and execute a command through subprocess.

    :param attempts:        How many times to retry running the command.
    :param binary:          On Python 3, return stdout and stderr as bytes if
                            binary is True, as Unicode otherwise.
    :param check_exit_code: Single bool, int, or list of allowed exit
                            codes.  Defaults to [0].  Raise
                            :class:`CalledProcessError` unless
                            program exits with one of these code.
    :param command:         The command passed to the subprocess.Popen.
    :param cwd:             Set the current working directory
    :param env_variables:   Environment variables and their values that
                            will be set for the process.
    :param retry_interval:  Interval between execute attempts, in seconds
    :param shell:           whether or not there should be a shell used to
                            execute this command.

    :raises:                :class:`subprocess.CalledProcessError`
    """
    # pylint: disable=too-many-locals

    attempts = kwargs.pop("attempts", ATTEMPTS)
    binary = kwargs.pop('binary', False)
    check_exit_code = kwargs.pop('check_exit_code', [0])
    cwd = kwargs.pop('cwd', None)
    env_variables = kwargs.pop("env_variables", None)
    retry_interval = kwargs.pop("retry_interval", RETRY_INTERVAL)
    shell = kwargs.pop("shell", False)

    command = [str(argument) for argument in command]
    ignore_exit_code = False

    if isinstance(check_exit_code, bool):
        ignore_exit_code = not check_exit_code
        check_exit_code = [0]
    elif isinstance(check_exit_code, int):
        check_exit_code = [check_exit_code]

    while attempts > 0:
        attempts = attempts - 1
        try:
            process = subprocess.Popen(command,
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, shell=shell,
                                       cwd=cwd, env=env_variables)
            result = process.communicate()
            return_code = process.returncode

            if six.PY3 and not binary and result is not None:
                # pylint: disable=no-member

                # Decode from the locale using using the surrogate escape error
                # handler (decoding cannot fail)
                (stdout, stderr) = result
                stdout = os.fsdecode(stdout)
                stderr = os.fsdecode(stderr)
            else:
                stdout, stderr = result

            if not ignore_exit_code and return_code not in check_exit_code:
                raise subprocess.CalledProcessError(returncode=return_code,
                                                    cmd=command,
                                                    output=(stdout, stderr))
            else:
                return (stdout, stderr)
        except subprocess.CalledProcessError:
            if attempts:
                time.sleep(retry_interval)
            else:
                raise

        raise RuntimeError("The maximum number of attempts has been exceeded.")
