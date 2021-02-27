"""

This script is used to pull the content of a git repository,
and upload it to a server via Secure File Transfer Protocol (SFTP).
This can be used when said server doesn't allow git commands.

"""

import os
import logging

# Third-party
import git  # pip install gitpython
import pysftp  # pip install pysftp

from typing import List
from functools import wraps
from datetime import datetime
from time import time, gmtime, strftime


def time_it(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        timer_start = time()
        returned = func(*args, *kwargs)
        timer_stop = time()

        result = timer_stop - timer_start

        logging.info(f"The function {func.__name__!r} took {result} seconds or {strftime('%H:%M:%S', gmtime(result))}.")

        return returned

    return wrapper


class GitSftp:

    # All the below values are case-sensitive.

    # Files with these extensions should not be copied. Do not include the leading dot.
    # e.g. ["iso", "mp4"]
    cp_excluded_ext: List[str] = []
    # Specific file names that should not be copied. Include the extension.
    # e.g. ["file.txt", "log.log"]
    cp_excluded_files_names: List[str] = ["git_sftp.py", "LICENSE.txt", ".gitignore"]
    # Files that should not be copied. Absolute paths only.
    # e.g. ["/this/file.txt", "that/specific/log.log"]
    cp_excluded_files: List[str] = []
    # Names of directories that should not be copied. Do not include the first or last separator (e.g. "/").
    # e.g. ["Dropbox", ".cache"]
    cp_excluded_directories_names: List[str] = [".git", ".idea", "__pycache__"]
    # Directories that should not be copied. Absolute paths only. Do not include the last separator (e.g. "/").
    # e.g. ["/proc", "/home/user/.cache"]
    cp_excluded_directories: List[str] = []

    # Files with these extensions should not be removed. Do not include the leading dot.
    rm_excluded_ext: List[str] = []
    # Specific file names that should not be removed. Include the extension.
    rm_excluded_files_names: List[str] = [".bash_logout", ".bash_profile", ".bashrc", ".ovhconfig"]
    # Files that should not be removed. Absolute paths only.
    rm_excluded_files: List[str] = []
    # Names of directories that should not be removed. Do not include the first or last separator.
    rm_excluded_directories_names: List[str] = []
    # Directories that should not be removed. Absolute paths only. Do not include the last separator.
    rm_excluded_directories: List[str] = []

    def __init__(self, srv, src: str):
        """
        :param srv: A pysftp connection object.
        :param str src: The source directory path (absolute).
        """
        if not os.path.isabs(src):
            raise ValueError(f"The source path is not absolute: {src!r}.")

        self.srv = srv

        self._force_put: bool = False

        self.root_src = self.format_path(src)
        self.root_dst = self.format_path(self.srv.pwd)

        self.cp_process_ext: bool = len(self.cp_excluded_ext) > 0
        self.rm_process_ext: bool = len(self.rm_excluded_ext) > 0

    @staticmethod
    def format_path(path: str) -> str:

        def norm(p: str) -> str:
            return p.replace("\\", "/")

        path = norm(path)

        if not path.endswith("/"):
            path = path + "/"

        return path

    @staticmethod
    def git_pull() -> bool:
        """
        Launches a git pull on the current working directory.
        :return bool: True if there has been updates on the git repository, False otherwise.
        """
        g = git.cmd.Git(os.getcwd())
        s = g.pull()
        logging.debug(f"[DEBUG] Git return value: {s!r}")
        if s == 'Already up to date.':
            return False
        else:
            return True

    def remote_dir_exists(self, dr: str, create: bool = False) -> bool:
        logging.debug(f"[DEBUG] Checking for directory existence: {dr!r}.")
        if self.srv.exists(dr):
            if self.srv.isdir(dr):
                logging.debug(f"[DEBUG] Directory exists: {dr!r}.")
                return True
        else:
            if create:
                logging.info(f"[INFO] Creating directory tree {dr!r}.")
                self.srv.makedirs(dr)
                return True
        return False

    def force(self, b: bool) -> None:
        """
        This method is used to change the force_put attribute, which dictates how the file put (the upload) behaves.
        If the force is set to True, the system will override all files on the server without checking.
        It is suited for high-capacity bandwidths.
        As much as you can, let it switched on False (the default).
        """
        self._force_put = b

    # Copy section

    @time_it
    def copy(self) -> None:
        self.put_dir(self.root_src, self.root_dst)

    def put_dir(self, src: str, dst: str) -> None:
        """
        Copies a directory via SFTP.

        :param str src: Absolute path of the directory to copy.
        :param str dst: Absolute path of the destination directory.
        """
        logging.debug(f"[DEBUG] Processing directory {src!r}")

        dst_exists = None
        for item in os.listdir(src):
            item_local_path = os.path.join(self.format_path(src), item)
            item_remote_path = os.path.join(self.format_path(dst), item)

            if os.path.isdir(item_local_path):
                if item in self.cp_excluded_directories_names:
                    continue
                if item_local_path in self.cp_excluded_directories:
                    continue
                self.put_dir(item_local_path, item_remote_path)

            elif os.path.isfile(item_local_path):
                if item in self.cp_excluded_files_names:
                    continue
                if item_local_path in self.cp_excluded_files:
                    continue
                if self.cp_process_ext:
                    ext = item.split(".")[-1]
                    if ext in self.cp_excluded_ext:
                        continue
                if not dst_exists:
                    dst_exists = self.remote_dir_exists(dst, create=True)
                self.put_file(item_local_path, item_remote_path)

    def put_file(self, src: str, dst: str) -> None:
        """
        Copies a file to a directory.
        src is the original file to copy in place of dst.

        :param str src: Absolute path of the file to copy.
        :param str dst: Absolute path of the file's destination (including the file name and extension).
        """
        logging.debug(f"[DEBUG] Processing file {src!r}")

        dst_file_already_exist = self.srv.isfile(dst)
        additional_status = ""

        if not self._force_put:
            # If the file already exists in the destination
            if dst_file_already_exist:
                # Gather information on the src and dst files.
                src_stats = os.stat(src)
                dst_stats = self.srv.stat(dst)
                src_last_mod = src_stats.st_mtime
                dst_last_mod = dst_stats.st_mtime
                src_size = src_stats.st_size
                dst_size = dst_stats.st_size

                # If neither the modification date nor the file size changed, return.
                if not src_last_mod > dst_last_mod:
                    return
                if not src_size != dst_size:
                    return

        status = "Updated" if dst_file_already_exist else "Copied"

        try:
            self.srv.put(src, dst)
        except PermissionError:
            logging.warning(f"[PermissionsError] Could not copy file {src!r}")
        except OSError:
            logging.warning(f"[OSError] Could not copy file {src!r}")
        except UnicodeEncodeError:
            logging.warning(f"[UnicodeEncodeError] Could not copy file {src!r}")
        else:
            logging.info(f"[INFO] {status} file {src!r} to {dst!r}{additional_status}.")

    # Clean section

    @time_it
    def clean(self) -> None:
        self.dir_clean(self.root_dst, self.root_src)

    def dir_clean(self, src: str, dst: str) -> None:
        """
        Cleans a directory and its content.
        Used recursively.
        In this case, src is the remote directory, and dst is the local path.

        :param str src: Absolute path to the remote directory.
        :param str dst: Absolute path to the original directory.
        """

        def remove_dir(dr: str, force: bool = False) -> None:
            if force:
                self.srv.rmdir(dir)
            else:
                try:
                    os.rmdir(dr)
                except (FileNotFoundError, OSError) as e:
                    logging.debug(f"[DEBUG] Caught exception while trying to remove directory {dr!r}: {e!r}")
                    pass
                except PermissionError:
                    logging.warning(f'[PermissionError] Could not delete directory {dr!r}.')
                else:
                    logging.info(f"[INFO] Removed directory {dr!r}.")

        logging.debug(f"[DEBUG] Processing directory {src!r}")

        for item in self.srv.listdir(src):
            item_remote_path = os.path.join(self.format_path(src), item)
            item_local_path = os.path.join(self.format_path(dst), item)

            if self.srv.isdir(item_remote_path):
                if item in self.cp_excluded_directories_names:
                    continue
                if item_remote_path in self.cp_excluded_directories:
                    continue
                self.dir_clean(item_remote_path, item_local_path)
                if len(self.srv.listdir(item_remote_path)) == 0:
                    # We can remove the directory if it has no children after the cleaning process
                    remove_dir(item_remote_path)

            elif os.path.isfile(item_remote_path):
                if item in self.rm_excluded_files_names:
                    continue
                if item_remote_path in self.rm_excluded_files:
                    continue
                if self.rm_process_ext:
                    ext = item.split(".")[-1]
                    if ext in self.rm_excluded_ext:
                        continue
                if not os.path.isfile(item_local_path):
                    # If the original file doesn't exist, we remove its copy.
                    self.file_clean(item_remote_path)

    def file_clean(self, src: str) -> None:
        """
        Tries to clean a file from a directory.
        In this case, src is a file from the RAID directory, and dst is the original file's path.

        :param str src: Absolute path of the file to remove.
        """
        logging.debug(f"[DEBUG] Processing file {src!r}")

        try:
            self.srv.remove(src)
        except PermissionError:
            logging.info(f"[PermissionsError] Could not remove file {src!r}")
        else:
            logging.info(f"[INFO] Removed file {src!r}")


###########
# LOGGING #
###########


def create_log_file(log_dir: str, log_path: str) -> None:
    if not os.path.isabs(log_dir) or not os.path.isabs(log_path):
        raise ValueError("The log path must be absolute.")
    try:
        os.makedirs(log_dir)
    except FileExistsError:
        pass
    open(log_path, "w").close()


def get_log_file():
    now = datetime.now()
    year = now.year
    month = now.month.__str__().rjust(2, '0')
    day = now.day.__str__().rjust(2, '0')
    hour = now.hour.__str__().rjust(2, '0')
    minute = now.minute.__str__().rjust(2, '0')
    log_file = os.path.join(log_dst, f"pyGitSftp-{year}-{month}-{day}--{hour}-{minute}.txt")
    return log_file


log_dst = "/var/log/pyGitSftp/"

logfile = get_log_file()

create_log_file(log_dst, logfile)

# Setup the configuration for logging.
logging.basicConfig(
    format=u'%(asctime)s - %(message)s',  # We add a timestamp to each log entries.
    level=logging.INFO,
    datefmt='%m/%d/%Y %I:%M:%S %p',
    filename=logfile,
    filemode="w",
)


########
# MAIN #
########


srv_args = {  # Environment variables are set in /etc/environment
    "host": os.environ['SFTP_HOST'],
    "port": int(os.environ['SFTP_PORT']),
    "username": os.environ['SFTP_USERNAME'],
    "password": os.environ['SFTP_PASSWORD'],
    # "log": "/var/log/pyGitSftp.log",  # Uncomment this argument to override the logging configuration above.
}


def main() -> bool:
    src = os.getcwd()
    with pysftp.Connection(**srv_args) as srv:
        git_sftp = GitSftp(srv, src)
        if git_sftp.git_pull():  # If the git repository had updates.
            git_sftp.force(False)
            git_sftp.copy()
            git_sftp.clean()
            delete_log = False
        else:
            delete_log = True
        return delete_log


if __name__ == "__main__":
    del_log = main()
    if del_log:
        os.remove(logfile)

