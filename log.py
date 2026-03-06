# -*- coding: utf-8 -*-
"""全局日志
Note: 仅在入口文件中导入一次
"""
import os
import datetime
import logging
import sys
import threading


def get_submod_log(submod_name):
    return logging.getLogger('Main' + '.' + submod_name)


class LoggerStream(object):
    """假 stream，将 stdout/stderr 流重定向到日志，避免win上无头模式运行时报错。
    ref: https://docs.python.org/3/library/sys.html#sys.__stdout__
    """
    _guard = threading.local()

    def __init__(self, name, level, fileno, fallback_stream=None):
        """
        :param logger: 日志实例
        :param level: 日志等级
        """
        self.logger = get_submod_log(name)
        self.level = level
        self._fileno = fileno
        self._fallback_stream = fallback_stream

    def fileno(self):
        return self._fileno

    def _fallback_write(self, text):
        if not text:
            return

        stream = self._fallback_stream
        if stream is None or not hasattr(stream, 'write'):
            return

        try:
            stream.write(text)
            if hasattr(stream, 'flush'):
                stream.flush()
        except Exception:
            pass

    def write(self, lines):
        if not lines:
            return 0

        text = str(lines)
        if getattr(self._guard, 'active', False):
            self._fallback_write(text)
            return len(text)

        try:
            self._guard.active = True
            for line in text.splitlines():
                if line.strip():
                    self.logger.log(self.level, line)
        except Exception:
            self._fallback_write(text)
        finally:
            self._guard.active = False

        return len(text)

    def flush(self):
        for handler in self.logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass

        if self._fallback_stream is not None and hasattr(self._fallback_stream, 'flush'):
            try:
                self._fallback_stream.flush()
            except Exception:
                pass


def init_log(application_path):
    log_path = os.path.join(application_path, r'logs/log-%s.txt' % (datetime.datetime.today().strftime('%Y-%m-%d')))
    stdout_stream = sys.__stdout__ or sys.stdout
    stderr_stream = sys.__stderr__ or sys.stderr

    handlers = [logging.FileHandler(log_path, 'w', 'utf-8')]
    if stderr_stream and hasattr(stderr_stream, 'write'):
        handlers.append(logging.StreamHandler(stderr_stream))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.raiseExceptions = False

    sys.stdout = LoggerStream('STDOUT', logging.INFO, 1, fallback_stream=stdout_stream)
    sys.stderr = LoggerStream('STDERR', logging.ERROR, 2, fallback_stream=stderr_stream)


