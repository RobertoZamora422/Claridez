"""Renderer aislado y terminable: no hereda conexiones PostgreSQL ni un tenant scope."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection

from .renderers import ExportDataset, render
from .storage import MAX_ARTIFACT_BYTES


def _child(sender: Connection, dataset: ExportDataset, format_name: str) -> None:
    try:
        sender.send_bytes(b"ok:" + render(dataset, format_name))
    except ValueError:
        sender.send_bytes(b"invalid:")
    except Exception:
        # El padre conserva solo un código; nunca mensajes con contenido del dataset.
        sender.send_bytes(b"failed:")
    finally:
        sender.close()


def render_bounded(dataset: ExportDataset, format_name: str, *, timeout_seconds: float) -> bytes:
    if timeout_seconds <= 0:
        raise ValueError("export_time_limit")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(sender, dataset, format_name), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout_seconds):
            raise ValueError("export_time_limit")
        try:
            packet = receiver.recv_bytes(MAX_ARTIFACT_BYTES + 8)
        except (EOFError, OSError) as error:
            raise OSError("renderer_process_unavailable") from error
        if packet == b"invalid:":
            raise ValueError("export_contract_or_limit_failure")
        if not packet.startswith(b"ok:"):
            raise OSError("renderer_process_unavailable")
        return packet[3:]
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            process.close()
