"""Log uncaught application and thread failures without exception payloads."""

import logging
import sys
import threading

_previous_hook = sys.excepthook
_previous_thread_hook = threading.excepthook


def _log_uncaught(error_type, error, trace):
    if issubclass(error_type, (KeyboardInterrupt, SystemExit)):
        _previous_hook(error_type, error, trace)
        return
    logging.getLogger(__name__).error("Unhandled application exception", exc_info=(error_type, error, trace))


def _log_thread(args):
    if not issubclass(args.exc_type, SystemExit):
        logging.getLogger(__name__).error("Unhandled thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    if _previous_thread_hook is not threading.__excepthook__:
        _previous_thread_hook(args)


def install_exception_hooks():
    global _previous_hook, _previous_thread_hook
    if sys.excepthook is not _log_uncaught:
        _previous_hook = sys.excepthook
        sys.excepthook = _log_uncaught
    if threading.excepthook is not _log_thread:
        _previous_thread_hook = threading.excepthook
        threading.excepthook = _log_thread
