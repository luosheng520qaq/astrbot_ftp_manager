from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import aioftp
from pathlib import PurePosixPath


@register("astrbot_plugin_ftp_control", "Xican", "FTP 控制工具，通过 LLM 工具执行文件操作", "1.0.0")
class FtpControlPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    @filter.llm_tool(name="ftp_manage")
    async def ftp_manage(self, event: AstrMessageEvent, operation: str, server_path: str, local_path: str = "", new_name: str = ""):
        '''将文件与网络服务器进行交互，支持上传、下载、删除、重命名、创建目录、列出目录内容等操作，此工具能够将文件转为对应的网络url。
        此工具能够将文件转为对应的网络url

        Args:
            operation(string): 操作类型，可选 upload, download, delete, rename, mkdir, list
            server_path(string): 服务器上的路径
            local_path(string): 本地文件路径
            new_name(string): 新名字（用于重命名）
        '''
        try:
            outcome = await self._do_ftp(operation, server_path, local_path, new_name)
            text = outcome.get("message", "操作完成")
            await event.send(event.plain_result(text))
            return outcome
        except Exception as e:
            logger.error(f"ftp_manage error: {e}")
            await event.send(event.plain_result(f"FTP操作失败: {e}"))
            return {"ok": False, "error": str(e), "operation": operation, "server_path": server_path}

    async def _do_ftp(self, operation: str, server_path: str, local_path: str, new_name: str):
        cfg = self.config or {}
        server = cfg.get("server", {})
        host = server.get("ip", "")
        port = int(server.get("port", 21))
        user = server.get("username", "")
        password = server.get("password", "")
        root_dir = cfg.get("ftp_root_dir", "/")
        base_url = cfg.get("base_access_url", "")
        remote_path = str(PurePosixPath(root_dir) / PurePosixPath(server_path.lstrip("/")))
        async with aioftp.Client.context(host, port=port, user=user, password=password) as client:
            if operation == "upload":
                await client.upload(local_path, remote_path, write_into=True)
                url = self._build_url(base_url, root_dir, remote_path)
                return {"ok": True, "operation": operation, "remote_path": remote_path, "url": url, "message": f"已上传到 {remote_path}" + (f" 可访问: {url}" if url else "")}
            if operation == "download":
                await client.download(remote_path, local_path, write_into=True)
                return {"ok": True, "operation": operation, "remote_path": remote_path, "local_path": local_path, "message": f"已下载到 {local_path}"}
            if operation == "delete":
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
        except Exception:
            return ""