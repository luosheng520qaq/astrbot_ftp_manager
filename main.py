from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import aioftp
from pathlib import PurePosixPath
import os


@register("astrbot_plugin_ftp_control", "Xican", "FTP 控制工具，通过 LLM 工具执行文件操作", "1.0.0")
class FtpControlPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    @filter.llm_tool(name="ftp_manage")
    async def ftp_manage(self, event: AstrMessageEvent, operation: str, server_path: str = "/", local_path: str = "", new_name: str = ""):
        '''将文件与网络服务器进行交互，支持上传、下载、删除、重命名、创建目录、列出目录内容等操作，此工具能够将文件转为对应的网络url。
        此工具能够将文件转为对应的网络url

        Args:
            operation(string): 操作类型，可选 upload, download, delete, rename, mkdir, list
            server_path(string): 服务器上的路径
            local_path(string): 本地文件路径(只能是绝对路径)
            new_name(string): 新名字（用于重命名）
        '''
        try:
            outcome = await self._do_ftp(operation, server_path, local_path, new_name)
            text = outcome.get("message", "操作完成")
            await event.send(event.plain_result(text))
            return outcome
        except aioftp.StatusCodeError as e:
            msg = f"FTP状态错误: 期望{tuple(e.expected_codes)}, 实际{tuple(e.received_codes)}, 信息: {e.info}"
            await event.send(event.plain_result(msg))
            return {"ok": False, "error": "StatusCodeError", "expected": tuple(e.expected_codes), "received": tuple(e.received_codes), "info": e.info, "operation": operation, "server_path": server_path}
        except FileNotFoundError as e:
            await event.send(event.plain_result(f"本地文件不存在: {e}"))
            return {"ok": False, "error": "FileNotFoundError", "detail": str(e), "operation": operation, "server_path": server_path, "local_path": local_path}
        except PermissionError as e:
            await event.send(event.plain_result(f"权限不足: {e}"))
            return {"ok": False, "error": "PermissionError", "detail": str(e), "operation": operation, "server_path": server_path, "local_path": local_path}
        except ValueError as e:
            await event.send(event.plain_result(f"参数错误: {e}"))
            return {"ok": False, "error": "ValueError", "detail": str(e), "operation": operation, "server_path": server_path}
        except OSError as e:
            await event.send(event.plain_result(f"系统错误: {e}"))
            return {"ok": False, "error": "OSError", "detail": str(e), "operation": operation, "server_path": server_path, "local_path": local_path}

    async def _do_ftp(self, operation: str, server_path: str, local_path: str, new_name: str):
        cfg = self.config or {}
        server = cfg.get("server", {})
        host = server.get("ip", "")
        port = int(server.get("port", 21))
        user = server.get("username", "")
        password = server.get("password", "")
        root_dir = cfg.get("ftp_root_dir", "/")
        base_url = cfg.get("base_access_url", "")
        security = cfg.get("security", {})
        ftps_explicit = bool(security.get("ftps_explicit", False))
        ftps_implicit = bool(security.get("ftps_implicit", False))
        operation = (operation or "").strip().lower()
        server_path = server_path or "/"
        remote_path = str(PurePosixPath(root_dir) / PurePosixPath(server_path.lstrip("/")))
        ctx_kwargs = {"port": port, "user": user, "password": password}
        if ftps_implicit:
            ctx_kwargs["ssl"] = True
        if ftps_explicit:
            ctx_kwargs["upgrade_to_tls"] = True
        async with aioftp.Client.context(host, **ctx_kwargs) as client:
            if operation == "upload":
                if not local_path:
                    raise ValueError("缺少 local_path")
                await client.upload(local_path, remote_path, write_into=True)
                local_name = os.path.basename(local_path)
                is_dir_target = (server_path.strip() in ("", "/")) or server_path.strip().endswith("/")
                dest_remote = str(PurePosixPath(remote_path) / local_name) if is_dir_target else remote_path
                url = self._build_url(base_url, root_dir, dest_remote)
                return {"ok": True, "operation": operation, "remote_path": dest_remote, "url": url, "message": f"已上传到 {dest_remote}" + (f" 可访问: {url}" if url else "")}
            if operation == "download":
                if not server_path or server_path.strip() in ("", "/"):
                    raise ValueError("下载操作需要指定服务器路径")
                if not local_path:
                    local_path = "."
                await client.download(remote_path, local_path, write_into=True)
                # 生成更友好的本地目标提示
                basename = PurePosixPath(server_path).name
                dest_local = os.path.join(local_path, basename) if os.path.isdir(local_path) or local_path in (".", "./") else local_path
                return {"ok": True, "operation": operation, "remote_path": remote_path, "local_path": dest_local, "message": f"已下载到 {dest_local}"}
            if operation == "delete":
                if server_path.strip() in ("", "/") or remote_path.strip("/") == PurePosixPath(root_dir).as_posix().strip("/"):
                    raise ValueError("禁止删除根目录")
                await client.remove(remote_path)
                return {"ok": True, "operation": operation, "remote_path": remote_path, "message": f"已删除 {remote_path}"}
            if operation == "rename":
                if not new_name:
                    raise ValueError("缺少 new_name")
                dest = str(PurePosixPath(remote_path).with_name(new_name))
                await client.rename(remote_path, dest)
                url = self._build_url(base_url, root_dir, dest)
                return {"ok": True, "operation": operation, "remote_path": dest, "url": url, "message": f"已重命名为 {dest}" + (f" 可访问: {url}" if url else "")}
            if operation == "mkdir":
                if server_path.strip() in ("", "/"):
                    raise ValueError("mkdir 需要指定新目录路径")
                await client.make_directory(remote_path)
                return {"ok": True, "operation": operation, "remote_path": remote_path, "message": f"已创建目录 {remote_path}"}
            if operation == "list":
                entries = await client.list(remote_path)
                names = [str(p) for p, _ in entries]
                msg = "\n".join(names) if names else f"{remote_path} 为空"
                return {"ok": True, "operation": operation, "remote_path": remote_path, "items": names, "message": msg}
            raise ValueError("不支持的操作")

    def _build_url(self, base_url: str, root_dir: str, remote_path: str) -> str:
        if not base_url:
            return ""
        try:
            rp = PurePosixPath(remote_path)
            root = PurePosixPath(root_dir)
            rel = rp.relative_to(root)
            return base_url.rstrip("/") + "/" + str(rel)
        except ValueError:
            return ""
