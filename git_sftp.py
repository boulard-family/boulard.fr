import os
import sys
import logging

# Third-party
import git   # pip install gitpython
import pysftp  # pip install pysftp


def set_logging(func):
    def wrapper(*args, **kwargs):
        logging_level = logging.DEBUG

        logger = logging.getLogger()
        logger.setLevel(logging_level)

        formatter = logging.Formatter('%(asctime)s - [%(levelname)s] %(message)s')
        formatter.datefmt = '%m/%d/%Y %H:%M:%S'

        # fh = logging.FileHandler(filename='C:/Temp/sami/sami.log', mode='w')
        # fh.setLevel(logging_level)
        # h.setFormatter(formatter)

        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging_level)
        sh.setFormatter(formatter)

        # logger.addHandler(fh)
        logger.addHandler(sh)

        return func(*args, **kwargs)
    return wrapper


def get_file_directory(file_path: str, sep: str = os.sep) -> str:
    path_parts = file_path.split(sep)
    file_name = path_parts.pop(-1)
    path = os.path.join(*path_parts)
    return path


def remote_dir_exists(srv, directory_path: str, create: bool = False) -> bool:
    if srv.exists(directory_path):
        if srv.isdir(directory_path):
            return True
    else:
        if create:
            srv.makedirs(directory_path)
            return True
    return False


def process_diff(srv, diff: git.Diff):

    def local_relative_path_to_absolute_path(local_relative_file_path: str) -> str:
        return os.path.join(os.getcwd(), local_relative_file_path)

    def remote_relative_path_to_absolute_path(srv, local_relative_file_path: str) -> str:
        return os.path.join(srv.pwd, local_relative_file_path)

    def upload_file(srv, local_file_path: str, remote_file_path: str) -> None:
        directory = get_file_directory(remote_file_path)
        remote_dir_exists(srv, directory, create=True)
        srv.put(local_file_path, remote_file_path)

    def delete_file(srv, remote_file_path: str) -> None:
        try:
            srv.remove(remote_file_path)
        except FileNotFoundError:
            logging.warning(f'Tried to remove {remote_file_path!r}, but got a "not found" error.')

    status = str(diff)
    status_parts = status.split('\n')
    file_relative_path = status_parts[0]
    local = local_relative_path_to_absolute_path(file_relative_path)
    remote = remote_relative_path_to_absolute_path(srv, file_relative_path)

    if diff.change_type == "A" and diff.new_file:
        # File was added.
        upload_file(srv, local, remote)
    elif diff.change_type == "D" and diff.deleted_file:
        # File was deleted.
        delete_file(srv, remote)
    elif diff.change_type == "C" and diff.copied_file:
        # File was copied from another.
        upload_file(srv, local, remote)
    elif diff.change_type == "R" and diff.renamed:
        # File was renamed.
        delete_file(srv, remote)
        upload_file(srv, local, remote)
    elif diff.change_type == "M" and diff.a_blob and diff.b_blob and diff.a_blob != diff.b_blob:
        # File was modified.
        delete_file(srv, remote)
        upload_file(srv, local, remote)


@set_logging
def main() -> None:
    srv_args = {  # Environment variables are set in /etc/environment
        "host": os.environ['SFTP_HOST'],
        "port": int(os.environ['SFTP_PORT']),
        "username": os.environ['SFTP_USERNAME'],
        "password": os.environ['SFTP_PASSWORD'],
        # "log": "/var/log/pyGitSftp.log",  # Uncomment this argument to overwrite the logging configuration.
    }
    repo = git.Repo(os.getcwd())
    if repo.bare:
        raise RuntimeError(f"Could not load git repository in directory {os.getcwd()!r}.")
    init_commit = repo.head.commit.tree  # SHA256
    fetch_info = repo.remote().pull()[0]
    diff: git.DiffIndex = git.Diffable.diff(init_commit)
    if len(diff) > 0:
        with pysftp.Connection(**srv_args) as srv:
            for diff_obj in diff:
                process_diff(srv, diff_obj)


if __name__ == "__main__":
    # Validate operating system
    if sys.platform != 'linux':
        input(f'This script was designed for Linux (detected OS: {sys.platform!r}), press enter to continue anyway...')
    main()
