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
BCBIO = "https://conda.binstar.org/bcbio"
BCBIO_DEV = "https://conda.binstar.org/bcbio-dev"
CONFIG = {}
RETRY_INTERVAL = 0.1
RECIPE = collections.namedtuple("Recipe", ["name", "path", "build", "version"])


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

    for recipe in ("azure-sdk-for-python", "prettytable",
                   "bcbio-nextgen", "bcbio-nextgen-vm"):
        recipe_path = os.path.join(path, recipe, "meta.yaml")
        if not os.path.isfile(recipe_path):
            continue

        output_path, _ = execute(["conda", "build", "--output", recipe],
                                 cwd=CONFIG["abspath"])
        with open(recipe_path, "r") as recipe_handle:
            config = yaml.safe_load(recipe_handle)
            recipes.append(RECIPE(
                name=recipe,
                path=output_path.strip(),
                version=toolz.get_in(["package", "version"], config),
                build=toolz.get_in(["build", "number"], config, 0),
            ))
    return recipes


def build_recipe(recipe, numpy, upload=False):
    """Build a new package for conda.

    :param recipe:  an isinstance of Recipe namedtuple
    :param numpy:   numpy version used by conda build
    :param upload:  whether to upload conda packages to binstars
    """
    command = ["conda", "build"]
    if numpy:
        command.extend(["--numpy", numpy])
    if not upload:
        command.append("--no-binstar-upload")
    command.append(recipe.name)

    try:
        execute(command, check_exit_code=True, cwd=CONFIG["abspath"])
    except subprocess.CalledProcessError as exc:
        if not CONFIG["quiet"]:
            print("Failed to upload the recipe {name}: {code}"
                  .format(name=recipe.name, code=exc.returncode))
            print("Command output: {output}".format(output=exc.output))
        raise


def upload_package(recipe, token):
    """Upload the package for the received recipe to the binstar.

    :param recipe:  an isinstance of Recipe namedtuple
    :param token:   authentication token to use
    """
    if not CONFIG["quiet"]:
        print("[i] Upload {recipe} to binstar.".format(recipe=recipe.name))

    command = ["binstar", "--token", token, "upload",
               "--channel", BCBIO_DEV, "--force", recipe.path]

    try:
        execute(command, check_exit_code=True, cwd=CONFIG["abspath"])
    except subprocess.CalledProcessError as exc:
        if not CONFIG["quiet"]:
            print("Failed to upload the recipe {name}: {code}"
                  .format(name=recipe.name, code=exc.returncode))
            print("Command output: {output}".format(output=exc.output))
        raise


def update_branch(branch_name, recipe="bcbio-nextgen-vm"):
    """Update the branch from the received recipe."""
    config = {}
    recipe_path = os.path.join(CONFIG["abspath"], recipe, "meta.yaml")
    if not os.path.isfile(recipe_path):
        return

    with open(recipe_path, "r") as recipe_handle:
        config = yaml.safe_load(recipe_handle)
        config["source"]["git_tag"] = branch_name

    if config:
        with open(recipe_path, "w") as recipe_handle:
            content = yaml.dump(config, indent=4, canonical=True)
            recipe_handle.write(content)


def main():
    """Run the command line application."""
    parser = argparse.ArgumentParser(
        description="Build and update conda packages on binstars "
                    "with latest versions")
    parser.add_argument(
        "-u", "--upload", dest="upload", action="store_true",
        default=False, help="upload conda packages to binstars.")
    parser.add_argument(
        "-b", "--branch", dest="branch", default="develop",
        help="the bcbio-nextgen-vm branch.")
    parser.add_argument(
        "-t", "--token", dest="token", default=None,
        help="authentication token to use, may be a token or a path"
             "to a file containing a token")
    parser.add_argument(
        "-n", "--numpy", dest="numpy", default=19,
        help="numpy version used by conda build")
    parser.add_argument(
        "-q", "--quiet", dest="quiet", action="store_true",
        default=False)

    args = parser.parse_args()
    CONFIG["quiet"] = args.quiet
    CONFIG["abspath"] = os.path.dirname(os.path.abspath(sys.argv[0]))

    if args.upload and not args.token:
        raise RuntimeError("No authentication token provided.")

    execute(["conda", "config", "--add", "channels", BCBIO],
            check_exit_code=True, cwd=CONFIG["abspath"])

    update_branch(args.branch)
    for recipe in get_recipes():
        build_recipe(recipe, args.numpy)
        if args.upload:
            upload_package(recipe, args.token)


if __name__ == "__main__":
    main()
