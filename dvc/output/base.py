from __future__ import unicode_literals
from dvc.utils.compat import str

import re
from schema import Or, Optional

from dvc.exceptions import DvcException


class OutputDoesNotExistError(DvcException):
    def __init__(self, path):
        msg = "output '{}' does not exist".format(path)
        super(OutputDoesNotExistError, self).__init__(msg)


class OutputIsNotFileOrDirError(DvcException):
    def __init__(self, path):
        msg = "output '{}' is not a file or directory".format(path)
        super(OutputIsNotFileOrDirError, self).__init__(msg)


class OutputAlreadyTrackedError(DvcException):
    def __init__(self, path):
        msg = "output '{}' is already tracked by scm (e.g. git)".format(path)
        super(OutputAlreadyTrackedError, self).__init__(msg)


class OutputBase(object):
    IS_DEPENDENCY = False

    REMOTE = None

    PARAM_PATH = "path"
    PARAM_CACHE = "cache"
    PARAM_METRIC = "metric"
    PARAM_METRIC_TYPE = "type"
    PARAM_METRIC_XPATH = "xpath"

    METRIC_SCHEMA = Or(
        None,
        bool,
        {
            Optional(PARAM_METRIC_TYPE): Or(str, None),
            Optional(PARAM_METRIC_XPATH): Or(str, None),
        },
    )

    DoesNotExistError = OutputDoesNotExistError
    IsNotFileOrDirError = OutputIsNotFileOrDirError

    def __init__(
        self, stage, path, info=None, remote=None, cache=True, metric=False
    ):
        self.stage = stage
        self.repo = stage.repo
        self.url = path
        self.info = info
        self.remote = remote or self.REMOTE(self.repo, {})
        self.use_cache = False if self.IS_DEPENDENCY else cache
        self.metric = False if self.IS_DEPENDENCY else metric

        if (
            self.use_cache
            and getattr(self.repo.cache, self.REMOTE.scheme) is None
        ):
            raise DvcException(
                "no cache location setup for '{}' outputs.".format(
                    self.REMOTE.scheme
                )
            )

    def __repr__(self):
        return "{class_name}: '{url}'".format(
            class_name=type(self).__name__, url=(self.url or "No url")
        )

    def __str__(self):
        return self.url

    @classmethod
    def match(cls, url):
        return re.match(cls.REMOTE.REGEX, url)

    def group(self, name):
        match = self.match(self.url)
        if not match:
            return None
        return match.group(name)

    @classmethod
    def supported(cls, url):
        return cls.match(url) is not None

    @property
    def scheme(self):
        return self.REMOTE.scheme

    @property
    def path(self):
        return self.path_info["path"]

    @property
    def sep(self):
        return "/"

    @property
    def checksum(self):
        return self.info.get(self.remote.PARAM_CHECKSUM)

    @property
    def exists(self):
        return self.remote.exists(self.path_info)

    def changed_checksum(self):
        return (
            self.checksum
            != self.remote.save_info(self.path_info)[
                self.remote.PARAM_CHECKSUM
            ]
        )

    def changed_cache(self):
        if not self.use_cache or not self.checksum:
            return True

        cache = self.repo.cache.__getattribute__(self.scheme)

        return cache.changed_cache(self.checksum)

    def status(self):
        if self.checksum and self.use_cache and self.changed_cache():
            return {str(self): "not in cache"}

        if not self.exists:
            return {str(self): "deleted"}

        if self.changed_checksum():
            return {str(self): "modified"}

        if not self.checksum:
            return {str(self): "new"}

        return {}

    def changed(self):
        return bool(self.status())

    def save(self):
        self.info = self.remote.save_info(self.path_info)

    def commit(self):
        if self.use_cache:
            getattr(self.repo.cache, self.scheme).save(
                self.path_info, self.info
            )

    def dumpd(self):
        ret = self.info.copy()
        ret[self.PARAM_PATH] = self.url

        if self.IS_DEPENDENCY:
            return ret

        ret[self.PARAM_CACHE] = self.use_cache

        if isinstance(self.metric, dict):
            if (
                self.PARAM_METRIC_XPATH in self.metric
                and not self.metric[self.PARAM_METRIC_XPATH]
            ):
                del self.metric[self.PARAM_METRIC_XPATH]

        ret[self.PARAM_METRIC] = self.metric

        return ret

    def download(self, to_info, resume=False):
        self.remote.download([self.path_info], [to_info], resume=resume)

    def checkout(self, force=False):
        if not self.use_cache:
            return

        getattr(self.repo.cache, self.scheme).checkout(
            self.path_info, self.info, force=force
        )

    def remove(self, ignore_remove=False):
        self.remote.remove(self.path_info)
        if self.scheme != "local":
            return

        if ignore_remove and self.use_cache and self.is_local:
            self.repo.scm.ignore_remove(self.path)

    def move(self, out):
        if self.scheme == "local" and self.use_cache and self.is_local:
            self.repo.scm.ignore_remove(self.path)

        self.remote.move(self.path_info, out.path_info)
        self.url = out.url
        self.path_info = out.path_info
        self.save()
        self.commit()

        if self.scheme == "local" and self.use_cache and self.is_local:
            self.repo.scm.ignore(self.path)
