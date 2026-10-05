# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Web Dashboard & Real-Time EXP Tracker.

This module intentionally contains only dashboard state + HTTP handlers so it can
be imported from Main.py without starting the bot by itself.
"""

import asyncio
import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from aiohttp import web

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "index.html")
ACCOUNTS_PATH = os.path.join(BASE_DIR, "accounts.json")


# Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level if level in {"info", "success", "warning", "error"} else "info",
            "message": str(message),
            "uid": str(uid) if uid is not None else None,
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        now = time.strftime("%H:%M:%S")
        safe_level = _safe_int(level, 1)
        safe_exp = _safe_int(exp, 0)
        safe_likes = _safe_int(likes, 0)

        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": (region or "BD").upper(),
                "level": safe_level,
                "initial_exp": safe_exp,
                "current_exp": safe_exp,
                "gained_exp": 0,
                "likes": safe_likes,
                "status": "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": now,
            }
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = str(region).upper()
            if safe_level > 0:
                acc["level"] = safe_level
            acc["current_exp"] = safe_exp
            # Preserve first seen EXP as the baseline for gained EXP.
            acc.setdefault("initial_exp", safe_exp)
            acc["gained_exp"] = max(0, safe_exp - _safe_int(acc.get("initial_exp"), 0))
            acc["likes"] = safe_likes
            if acc.get("status") in {"CONNECTING", "ERROR", "OFFLINE"}:
                acc["status"] = "ONLINE"
            acc["last_updated"] = now
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = _safe_int(acc.get("current_exp"), 0)
            current_exp = _safe_int(current_exp, old_exp)
            acc["current_exp"] = current_exp
            if level is not None and _safe_int(level, 0) > 0:
                acc["level"] = _safe_int(level, acc.get("level", 1))
            acc["gained_exp"] = max(0, current_exp - _safe_int(acc.get("initial_exp"), current_exp))
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                self.log(
                    f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total Gained: +{acc['gained_exp']}",
                    "success",
                    uid_str,
                )
            self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            status = (status or "UNKNOWN").upper()
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = max(0, _safe_int(active_matches, 0))
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(
                f"Account {self.accounts[uid_str]['nickname']} finished Match #{self.accounts[uid_str]['matches_played']}",
                "info",
                uid_str,
            )

    def remove_account_state(self, uid: str):
        uid_str = str(uid)
        if uid_str in self.accounts:
            del self.accounts[uid_str]
        self.recalc_totals()

    def recalc_totals(self):
        self.total_gained_exp = sum(_safe_int(acc.get("gained_exp"), 0) for acc in self.accounts.values())


bot_state = BotState()


# ==================== FILE HELPERS ====================

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_accounts_file() -> List[Dict[str, Any]]:
    if not os.path.exists(ACCOUNTS_PATH):
        return []
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            bot_state.log("accounts.json root must be a list; ignoring invalid content", "warning")
            return []
        return [item for item in data if isinstance(item, dict)]
    except Exception as exc:
        bot_state.log(f"Could not read accounts.json: {exc}", "error")
        return []


def _save_accounts_file(accounts: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(ACCOUNTS_PATH), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="accounts.", suffix=".tmp", dir=os.path.dirname(ACCOUNTS_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, ACCOUNTS_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _credential_for_uid(uid: str) -> Optional[Dict[str, Any]]:
    uid_str = str(uid)
    if uid_str in bot_state.account_credentials:
        return bot_state.account_credentials[uid_str]
    for data in bot_state.account_credentials.values():
        if not isinstance(data, dict):
            continue
        possible = {
            str(data.get("account_id", "")),
            str(data.get("auth_uid", "")),
        }
        token = data.get("auth_token")
        if token:
            possible.add(str(token))
            possible.add(str(token)[:10])
            possible.add(f"tok_{str(token)[:20]}")
        if uid_str in possible:
            return data
    return None


def _delete_saved_account(uid: str, credential: Optional[Dict[str, Any]]) -> bool:
    uid_str = str(uid)
    auth_uid = str(credential.get("auth_uid")) if credential and credential.get("auth_uid") else ""
    auth_token = str(credential.get("auth_token")) if credential and credential.get("auth_token") else ""
    account_id = str(credential.get("account_id")) if credential and credential.get("account_id") else uid_str

    existing = _load_accounts_file()
    kept: List[Dict[str, Any]] = []
    removed = False
    for acc in existing:
        saved_uid = str(acc.get("uid", ""))
        saved_token = str(acc.get("token", ""))
        should_remove = False
        if saved_uid and saved_uid in {uid_str, auth_uid, account_id}:
            should_remove = True
        if saved_token and (
            saved_token == uid_str
            or (auth_token and saved_token == auth_token)
            or f"tok_{saved_token[:20]}" == uid_str
            or saved_token[:10] == uid_str
        ):
            should_remove = True

        if should_remove:
            removed = True
        else:
            kept.append(acc)

    if removed:
        _save_accounts_file(kept)
    return removed


def _cancel_worker(uid: str, credential: Optional[Dict[str, Any]]) -> int:
    keys = {str(uid)}
    if credential:
        if credential.get("account_id"):
            keys.add(str(credential["account_id"]))
        if credential.get("auth_uid"):
            keys.add(str(credential["auth_uid"]))
        if credential.get("auth_token"):
            token = str(credential["auth_token"])
            keys.update({token[:10], f"tok_{token[:20]}", token})

    tasks = set()
    for key in keys:
        task = bot_state.account_workers.get(key)
        if task:
            tasks.add(task)

    cancelled = 0
    for task in tasks:
        if not task.done():
            task.cancel()
            cancelled += 1

    # Drop every alias that points to a cancelled task, plus direct keys.
    for key, task in list(bot_state.account_workers.items()):
        if key in keys or task in tasks:
            bot_state.account_workers.pop(key, None)

    return cancelled


def _drop_credentials(uid: str, credential: Optional[Dict[str, Any]]) -> None:
    targets = {str(uid)}
    if credential:
        if credential.get("account_id"):
            targets.add(str(credential["account_id"]))
        if credential.get("auth_uid"):
            targets.add(str(credential["auth_uid"]))
        if credential.get("auth_token"):
            token = str(credential["auth_token"])
            targets.update({token, token[:10], f"tok_{token[:20]}"})

    for key, data in list(bot_state.account_credentials.items()):
        if key in targets or (credential is not None and data is credential):
            bot_state.account_credentials.pop(key, None)


# ==================== HTTP HANDLERS ====================

async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = [dict(acc) for acc in bot_state.accounts.values()]
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    active_workers = len({id(task) for task in bot_state.account_workers.values() if not task.done()})
    return web.json_response(
        {
            "status": "ok",
            "total_accounts": len(bot_state.accounts),
            "total_matches": bot_state.total_matches,
            "total_gained_exp": bot_state.total_gained_exp,
            "active_workers": active_workers,
            "accounts": accounts_data,
            "logs": bot_state.logs[-80:],
            "uptime": int(time.time() - bot_state.start_time),
            "server_time": time.strftime("%H:%M:%S"),
        }
    )


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "error", "error": "Invalid JSON payload"}, status=400)

        if not isinstance(data, dict):
            return web.json_response({"status": "error", "error": "Payload must be an object"}, status=400)

        existing = _load_accounts_file()
        callback_payload: Dict[str, str]
        display_name: str

        if "uid" in data and "password" in data:
            uid = str(data.get("uid", "")).strip()
            pwd = str(data.get("password", "")).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"}, status=400)
            existing = [acc for acc in existing if str(acc.get("uid", "")) != uid]
            existing.append({"uid": uid, "password": pwd})
            callback_payload = {"uid": uid, "password": pwd}
            display_name = uid
            # Show immediate feedback while login completes.
            if uid not in bot_state.accounts:
                bot_state.register_account(uid, f"Guest {uid[-4:]}", "BD", 1, 0)
            bot_state.update_status(uid, "CONNECTING", 0)
        elif "token" in data:
            token = str(data.get("token", "")).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"}, status=400)
            existing = [acc for acc in existing if str(acc.get("token", "")) != token]
            existing.append({"token": token})
            callback_payload = {"token": token}
            display_name = f"token {token[:8]}..."
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"}, status=400)

        _save_accounts_file(existing)
        bot_state.log(f"Account saved: {display_name}", "success")

        # Trigger dynamic worker launch after the file has been safely saved.
        callback = bot_state.refresh_callbacks.get("on_account_added")
        if callback:
            task = asyncio.create_task(callback(callback_payload))

            def _callback_done(done_task: asyncio.Task):
                try:
                    exc = done_task.exception()
                    if exc:
                        bot_state.log(f"Account launcher failed: {exc}", "error")
                except asyncio.CancelledError:
                    pass

            task.add_done_callback(_callback_done)

        return web.json_response({"status": "ok", "message": "Account saved", "total_saved": len(existing)})
    except Exception as e:
        bot_state.log(f"Add account failed: {e}", "error")
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "error", "error": "Invalid JSON payload"}, status=400)

        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID is required"}, status=400)

        credential = _credential_for_uid(uid)
        removed_from_file = _delete_saved_account(uid, credential)
        cancelled_workers = _cancel_worker(uid, credential)

        # Remove visible account state. If this is a guest auth UID whose visible
        # account_id is different, remove that too.
        bot_state.remove_account_state(uid)
        if credential and credential.get("account_id"):
            bot_state.remove_account_state(str(credential["account_id"]))
        _drop_credentials(uid, credential)

        bot_state.log(
            f"Account {uid} removed. Saved entry: {'yes' if removed_from_file else 'no'}, workers stopped: {cancelled_workers}",
            "warning",
            uid,
        )
        return web.json_response(
            {
                "status": "ok",
                "removed_from_file": removed_from_file,
                "cancelled_workers": cancelled_workers,
            }
        )
    except Exception as e:
        bot_state.log(f"Delete account failed: {e}", "error")
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "error", "error": "Invalid JSON payload"}, status=400)

        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID is required"}, status=400)

        callback = bot_state.refresh_callbacks.get("on_refresh_account")
        if callback:
            asyncio.create_task(callback(uid))
            bot_state.log(f"Manual refresh requested for {uid}", "info", uid)
            return web.json_response({"status": "ok"})
        return web.json_response({"status": "error", "error": "Refresh callback is not ready yet"}, status=503)
    except Exception as e:
        bot_state.log(f"Refresh account failed: {e}", "error")
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://{host}:{port}\033[0m")
    return runner
