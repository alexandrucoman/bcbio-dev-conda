"""Update conda packages on binstars with latest versions"""
from __future__ import print_function

import argparse
import collections
import os
import six
import sys
import subprocess
import time
import yaml

import toolz

ATTEMPTS = 3
BCBIO_DEV = "bcbio-dev"
BCBIO_STABLE = "bcbio"
CONFIG = {}
RETRY_INTERVAL = 0.1
RECIPE = collections.namedtuple("Recipe", ["name", "path", "build", "version"])
RECIPE_ORDER = ("elasticluster", "bcbio-nextgen", "bcbio-nextgen-vm")

_REPO = "https://github.com/%s/%s"


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

    if cwd and not os.path.isdir(cwd):
        print("[w] Invalid value for cwd: {cwd}".format(cwd=cwd))
        cwd = None

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


def system_info():
    """Print information related to the environment."""
    if CONFIG["quiet"]:
        return

    conda_info, _ = execute(["conda", "info", "--all"])
    print("Conda info:\n{conda_info}".format(conda_info=conda_info))


def get_recipes(path=None):
    """Get all the available conda recipes.

    Returns a namedtuple which contains the following keys:
        :name:      the name of the recipe
        :path:      the path for the package
        :version:   the version of the recipe
        :build:     the number of builds for the current version
    """
    path = path or CONFIG["abspath"]
    recipes = []

    for recipe in RECIPE_ORDER:
        recipe_path = os.path.join(path, recipe, "meta.yaml")

        if not os.path.exists(recipe_path):
            print("[x] Missing meta.yaml for {recipe}.".format(recipe=recipe))
            continue

        output_path, _ = execute(["conda", "build", recipe, "--output",
                                  "--numpy", CONFIG["numpy"]], cwd=path)

        with open(recipe_path, "r") as recipe_handle:
            config = yaml.safe_load(recipe_handle)
            recipes.append(RECIPE(
                name=recipe,
                path=output_path.strip(),
                version=toolz.get_in(["package", "version"], config),
                build=toolz.get_in(["build", "number"], config, 0),
            ))
    return recipes


def build_recipe(recipe, upload=False):
    """Build a new package for conda.

    :param recipe:  an isinstance of Recipe namedtuple
    :param numpy:   numpy version used by conda build
    :param upload:  whether to upload conda packages to binstars
    """
    print("[i] Trying to build {recipe} recipe.".format(recipe=recipe))

    command = ["conda", "build", "--python", 27, recipe.name,
               "--numpy", CONFIG["numpy"]]

    if not upload:
        command.append("--no-anaconda-upload")

    try:
        execute(command, check_exit_code=True, cwd=CONFIG["abspath"])
    except subprocess.CalledProcessError as exc:
        print("[x] Failed to build the recipe {name}: {code}"
              .format(name=recipe.name, code=exc.returncode))

        if not CONFIG["quiet"]:
            # pylint: disable=unpacking-non-sequence
            stdout, stderr = exc.output
            print("[i] [STDOUT] Command output:\n{output}"
                  .format(output=stdout))
            print("[i] [STDERR] Command output:\n{output}"
                  .format(output=stderr))
        raise


def upload_package(recipe, token):
    """Upload the package for the received recipe to the binstar.

    :param recipe:  an isinstance of Recipe namedtuple
    :param token:   authentication token to use
    """
    if not CONFIG["quiet"]:
        print("[i] Uploading {recipe} to binstar.".format(recipe=recipe.name))

    command = ["binstar", "--token", token, "upload", "-u", BCBIO_DEV,
               "--channel", "main", "--channel", "linux-64",
               "--force", recipe.path]

    if not os.path.exists(recipe.path):
        print("[x] The recipe path is invalid: {recipe}"
              .format(recipe=recipe.path))
        return

    try:
        execute(command, check_exit_code=True, cwd=CONFIG["abspath"])
        if not CONFIG["quiet"]:
            print("[i] Package {} successfully uploaded.".format(recipe.name))

    except (subprocess.CalledProcessError, OSError) as exc:
        print("[x] Failed to upload the recipe {recipe}: {error}"
              .format(recipe=recipe, error=exc))

        if not CONFIG["quiet"] and hasattr(exc, "output"):
            # pylint: disable=unpacking-non-sequence
            stdout, stderr = exc.output
            print("[i] [STDOUT] Command output:\n{output}"
                  .format(output=stdout))
            print("[i] [STDERR] Command output:\n{output}"
                  .format(output=stderr))
        raise


def mock_recipe(recipe, mock):
    """Mock fields from the recipe with the recived mocked values."""
    if not CONFIG["quiet"]:
        print("[i] Mocking {recipe} with {mock}."
              .format(recipe=recipe, mock=mock))

    config = {}
    recipe_path = os.path.join(CONFIG["abspath"], recipe, "meta.yaml")
    if not os.path.exists(recipe_path):
        print("[x] The recipe path is invalid: {recipe}"
              .format(recipe=recipe_path))
        return

    with open(recipe_path, "r") as recipe_handle:
        config = yaml.safe_load(recipe_handle)

    if config and mock:
        config.update(mock)
        content = yaml.dump(config, indent=4, canonical=True)
        with open(recipe_path, "w") as recipe_handle:
            recipe_handle.write(content)


def add_channel(channel):
    """Add the received channel to conda channels."""
    try:
        execute(["conda", "config", "--add", "channels", channel],
                check_exit_code=True, cwd=CONFIG["abspath"])

        if not CONFIG["quiet"]:
            print("[i] Channel {} successfully added.".format(channel))

    except (subprocess.CalledProcessError, OSError) as exc:
        print("[x] Failed to add the channel {channel}: {error}"
              .format(channel=channel, error=exc))
        raise


def main():
    """Run the command line application."""
    parser = argparse.ArgumentParser(
        description="Build and update conda packages on binstars "
                    "with latest versions")
    parser.add_argument(
        "--bcbio-branch", dest="bcbio_branch", default="develop",
        help="the bcbio-nextgen-vm branch")
    parser.add_argument(
        "--bcbiovm-branch", dest="bcbiovm_branch", default="develop",
        help="the bcbio-nextgen-vm branch")
    parser.add_argument(
        "--username", dest="username", default="chapmanb",
        help="The owner of the bcbio repositories.")
    parser.add_argument(
        "-u", "--upload", dest="upload", action="store_true",
        default=False, help="upload conda packages to binstars.")
    parser.add_argument(
        "-t", "--token", dest="token", default=None,
        help="authentication token to use, may be a token or a path"
             "to a file containing a token")
    parser.add_argument(
        "-n", "--numpy", dest="numpy", default=110,
        help="numpy version used by conda build")
    parser.add_argument(
        "-q", "--quiet", dest="quiet", action="store_true",
        default=False)

    args = parser.parse_args()
    CONFIG["quiet"] = args.quiet
    CONFIG["abspath"] = os.path.dirname(os.path.abspath(sys.argv[0]))
    CONFIG["numpy"] = args.numpy

    if args.upload and not args.token:
        raise RuntimeError("No authentication token provided.")

    # Update the source from the bcbio-nextgen-vm recipe with the
    # values from the Travis-CI environment
    mocked_data = {
        "bcbio-nextgen-vm": {
            "source": {
                "git_url":  _REPO % (args.username, "bcbio-nextgen-vm"),
                "git_tag": args.bcbiovm_branch}
        },
        "bcbio-nextgen": {
            "source": {
                "git_url": _REPO % (args.username, "bcbio-nextgen"),
                "git_tag": args.bcbio_branch}
        },
    }

    for recipe in mocked_data:
        mock_recipe(recipe=recipe, mock=mocked_data[recipe])

    # Add the bcbio and bcbio-dev channels
    for channel in (BCBIO_STABLE, BCBIO_DEV):
        add_channel(channel)

    # Print system information before building the recipes
    system_info()

    # Build the conda recipes
    for recipe in get_recipes():
        build_recipe(recipe)
        if args.upload:
            upload_package(recipe, args.token)


if __name__ == "__main__":
    main()
