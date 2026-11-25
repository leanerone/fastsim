"""Translate engine exceptions into human-readable problems + fix hints.

Every user-facing failure path (REST send, scenario step) goes through
``explain_exception`` so the UI can show *what happened* and *what to do*
instead of a raw Python exception string.
"""
from __future__ import annotations

from ..engine.builtin.hsms import ConnectionLost, HsmsError, T3Timeout, T6Timeout
from ..engine.builtin.secs2 import SecsError
from ..engine.builtin.sml import SmlError


def _between(text: str, start: str, end: str) -> str:
    try:
        return text.split(start, 1)[1].split(end, 1)[0].strip()
    except (IndexError, ValueError):
        return ""


def _key_error(exc: KeyError) -> dict:
    key = str(exc.args[0]) if exc.args else ""
    lowered = key.lower()
    if "session not found" in lowered:
        return {"code": "SESSION_NOT_FOUND", "message": "会话不存在或已被删除",
                "hint": "回到“开始使用”重新创建会话。"}
    if "unknown" in lowered:
        return {"code": "UNDEFINED_ID", "message": f"机台 Profile 中没有定义：{key}",
                "hint": "在“机台配置”中查看已定义的报警、事件或变量 ID。"}
    return {"code": "NOT_FOUND", "message": f"找不到对象：{key}",
            "hint": "请确认引用的名称或 ID 正确。"}


def explain_exception(exc: BaseException) -> dict:
    """Return ``{code, message, hint}`` in Chinese for errors a user can act on.

    Unknown exceptions fall back to their raw text so nothing is swallowed.
    """
    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, SmlError):
        return {"code": "SML_INVALID", "message": f"SML 格式有误：{text}",
                "hint": "可以从消息库选择模板，或检查 < > 与引号是否成对、"
                        "类型名是否正确（如 <A \"R-1\">、<U4 1002>）。"}
    if isinstance(exc, T3Timeout):
        sf = _between(text, "reply for ", " sys")
        return {"code": "T3_TIMEOUT", "message": f"等待 {sf or '对端'} 应答超时（T3）",
                "hint": "对端在 T3 时间内没有应答。请确认对端支持该消息，"
                        "或适当调大 Profile 的 T3。"}
    if isinstance(exc, T6Timeout):
        return {"code": "T6_TIMEOUT", "message": "控制事务超时（T6），对端未应答握手或心跳",
                "hint": "链路可能不稳定，请查看工作台顶部的连接问题提示。"}
    if isinstance(exc, ConnectionLost) or "cannot send in state" in lowered \
            or "no connection" in lowered:
        if "not_connected" in lowered or "no connection" in lowered:
            return {"code": "NOT_CONNECTED", "message": "会话尚未建立连接，消息没有发出",
                    "hint": "请先确认链路已建立，工作台顶部会显示连接问题与解决办法。"}
        return {"code": "LINK_DOWN", "message": "连接已断开，消息没有发出",
                "hint": "链路恢复后会自动重连，请查看工作台顶部的连接问题提示。"}
    if isinstance(exc, KeyError):
        return _key_error(exc)
    if isinstance(exc, (HsmsError, SecsError)):
        return {"code": type(exc).__name__.upper(), "message": text}
    return {"code": "ERROR", "message": text}


def public_error(exc: BaseException) -> dict:
    """HTTP error body: friendly fields plus the raw text for debugging."""
    return {**explain_exception(exc), "raw": str(exc)}
