import datetime
import http.server
import json
import logging
import os
import sys
import time
import typing
import urllib.parse
from multiprocessing import Array
from multiprocessing import Process
from multiprocessing import Queue
from functools import wraps
import traceback
from multiprocessing import Value

from config import K8sConfig
from csm import MigrationCommands
from kube import K8sApiNative

DEBUG = os.environ.get("DEBUG", None) is not None
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


def catch_ex(fn):
    """
    :param fn: function whose first argument is a "link" class
    :return:
    """
    @wraps(fn)
    def wrap(*args, **kwargs):
        link: Link = args[0]
        try:
            link.rv = fn(*args, **kwargs)
            link.info("process completed normally")
        except Exception as e:
            tb = traceback.format_exc()
            link.error(tb)
            link.error(f"process terminated with exception: {e}")
            link.ok = False
    return wrap


class Link:
    def __init__(self, name: str, level=logging.DEBUG):
        self.create_time = datetime.datetime.utcnow().isoformat()
        self._name = name
        self._ok = Value('b', True)
        self._rv = Array('c', 2**14)    # return value, if any. should be json string
        self._messages = Queue()        # log messages from process
        self._level = level

    def _log(self, level: int, message: str):
        self._messages.put(f"{datetime.datetime.utcnow().isoformat()}::{logging.getLevelName(level)}:: {message}")
        logger.log(level, f"{self._name}:: {message}")

    def debug(self, m):
        self._log(logging.DEBUG, m)

    def info(self, m):
        self._log(logging.INFO, m)

    def warning(self, m):
        self._log(logging.WARNING, m)

    def error(self, m):
        self._log(logging.ERROR, m)

    def isEnabledFor(self, level):
        return level >= self._level

    @property
    def rv(self):
        v = str(self._rv.value, 'UTF-8')
        try:
            return json.loads(v)
        except:
            return v

    @rv.setter
    def rv(self, value: typing.Any):
        self._rv.value = bytes(json.dumps(value), 'UTF-8')

    @property
    def ok(self):
        return bool(self._ok.value)

    @ok.setter
    def ok(self, ok: bool=True):
        self._ok.value = ok

    def poll(self):
        acc = []
        while not self._messages.empty():
            acc.append(self._messages.get_nowait())
        return acc

    def close(self):
        self._messages.close()


@catch_ex
def _t_preflight(link, service):
    cfg = K8sConfig()
    commands = MigrationCommands(config=cfg, k8s=K8sApiNative(logger=link), logger=link)
    rv = commands.preflight(service)
    link.ok = rv['pass']
    return rv


@catch_ex
def _t_sync(link, service):
    cfg = K8sConfig()
    commands = MigrationCommands(config=cfg, k8s=K8sApiNative(logger=link), logger=link)
    commands.sync(service)


@catch_ex
def _t_cutover(link, service):
    cfg = K8sConfig()
    commands = MigrationCommands(config=cfg, k8s=K8sApiNative(logger=link), logger=link)
    commands.cutover(service)


@catch_ex
def _t_cleanup(link, service):
    cfg = K8sConfig()
    commands = MigrationCommands(config=cfg, k8s=K8sApiNative(logger=link), logger=link)
    commands.cleanup(service)


class ProcessManagementServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, targets):
        super().__init__(server_address, RequestHandlerClass)
        self._tasks = {}  # id -> (process, link, history,)
        self._targets = targets

    def serve_forever(self, **kwargs):
        super().serve_forever(**kwargs)


class RequestHandler(http.server.BaseHTTPRequestHandler):

    def __init__(self, request, client_address, server):
        super().__init__(request, client_address, server)

    def _check_task(self, id) -> typing.Optional[dict]:
        if id in self.server._tasks:
            p, link, history = self.server._tasks[id]
            history.extend(link.poll())
            state = "running" if p.is_alive() else "complete"
            task = {"state": state,
                    "createTime": link.create_time,
                    "messages": history}
            if state == "complete":
                task['ok'] = link.ok
                task['value'] = link.rv
            return task
        return None

    def _create_task(self, kind, arg) -> typing.Tuple[int, typing.Optional[dict]]:
        _id = f"{kind}/{arg}"
        res = self._check_task(_id)
        if res:
            return 409, {"error": "task already exists and must be deleted prior to recreating"},

        target_fn = self.server._targets[kind]
        link = Link(f"{_id}")
        p = Process(target=target_fn, args=(link, arg,))
        p.start()
        self.server._tasks[_id] = (p, link, [],)
        return 201, {"state": "started", "id": _id}

    def _delete_task(self, kind, arg) -> typing.Tuple[int, typing.Optional[dict]]:
        _id = f"{kind}/{arg}"
        p, link, history = self.server._tasks.get(_id, (None, None, None,))
        if not p:
            return 404, {"error": f"{_id} not found"}
        elif p.is_alive():
            p.terminate()
            del self.server._tasks[_id]
            return 200, {"state": "killed"}
        else:
            del self.server._tasks[_id]
            return 200, {"state": "deleted"}

    def _get_task(self, kind, arg) -> typing.Tuple[int, typing.Optional[dict]]:
        _id = f"{kind}/{arg}"
        res = self._check_task(_id)
        if res:
            return 200, res
        return 404, {"error": "not found"}

    def _list_tasks(self, kind=None, include_completed=True) -> typing.Tuple[int, typing.Optional[list]]:
        include_key = lambda key: kind is None or key.startswith(f"{kind}/")
        res = []
        for key in self.server._tasks.keys():
            if include_key(key):
                r = {**self._check_task(key), "id": key}
                del r["messages"]
                if not include_completed and r['state'] == "completed":
                    continue
                res.append(r)
        return 200, res

    def _send_json(self, status, body: typing.Any = None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if body is not None:
            self.wfile.write(bytes(json.dumps(body), encoding="UTF-8"))

    def _parse_path(self) -> typing.Tuple[typing.List[str], dict]:
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        if p == "/" or p == "":
            return [], q,
        return (p[1:].split("/"), q,) if p.startswith("/") else (p.split("/"), q,)

    def do_POST(self):
        path, qp = self._parse_path()
        if len(path) != 3 or path[0] != "tasks":
            self._send_json(404)
            return

        status, body = self._create_task(path[1], path[2])
        self._send_json(status, body)

    def do_GET(self):
        path, qp = self._parse_path()
        lp = len(path)
        if lp == 0:
            self._send_json(200, {"tasks": list(self.server._targets.keys())})
            return
        if (lp < 1 or lp > 3) or path[0] != "tasks":
            self._send_json(404)
            return
        if lp == 1 or lp == 2:
            status, body = self._list_tasks(path[1] if lp == 2 else None, include_completed=qp.get("include_completed", False))
        else:
            status, body = self._get_task(path[1], path[2])
        self._send_json(status, body)

    def do_DELETE(self):
        path, qp = self._parse_path()
        if len(path) != 3 or path[0] != "tasks":
            self._send_json(404)
            return
        kind, arg = path[1], path[2]
        status, body = self._delete_task(kind, arg)
        self._send_json(status, body)


@catch_ex
def _t_dummy(link, arg):
    t = int(arg)
    if t < 1:
        raise ValueError(f"values less than 1 are not supported: {t}")
    link.info(f"begin {t} for {t} iterations")
    for itr in range(t):
        link.info(f"{itr}")
        time.sleep(1)
    link.info(f"end {t}")


if __name__ == '__main__':
    port = int(os.environ.get("HTTP_PORT", "8080"))
    server = ProcessManagementServer(
        ('', port),
        RequestHandler,
        targets={"preflight": _t_preflight,
                 "sync": _t_sync,
                 "cutover": _t_cutover,
                 "cleanup": _t_cleanup,
                 "dummy": _t_dummy, })
    if DEBUG:
        logger.warning("running in debug mode")
    logger.info(f"server opening on {port}")
    try:
        server.serve_forever(poll_interval=0.05)
    except:
        logger.info("server closed")
