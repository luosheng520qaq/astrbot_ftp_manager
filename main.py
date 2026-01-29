from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import aioftp
from pathlib import PurePosixPath
import os
import ssl


@register("astrbot_plugin_ftp_control", "Xican", "FTP 控制工具，通过 LLM 工具执行文件操作", "1.0.0")
class FtpControlPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    @filter.llm_tool(name="ftp_manage")
    async def ftp_manage(self, event: AstrMessageEvent, operation: str, server_path: str = "/", local_path: str = "", new_name: str = ""):
        '''FTP 文件管理工具。

        Args:
            operation(string): 操作类型: upload, download, delete, rename, mkdir, list
            server_path(string): 服务器端路径。
                                 - upload: 强烈建议提供**完整的目标文件路径** (包含文件名和后缀)，例如 "/data/image.png"。
                                   * 若仅提供目录路径 (如 "/data" 或 "/data/")，系统将尝试自动推断，但为了准确性请尽量精确。
                                 - download/delete/rename: 目标文件或目录的完整路径。
                                 - mkdir/list: 目录路径。
            local_path(string): 本地文件绝对路径。
                                - upload: 必填 (源文件路径)。
                                - download: 可选 (若为空则下载到当前目录)。
            new_name(string): 新文件名 (仅 rename 操作需要)。
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
        ssl_verify = bool(security.get("ssl_verify", False))
        operation = (operation or "").strip().lower()
        
        server_path = server_path or "/"
        # 基础远程路径（可能是目录也可能是文件，取决于操作和上下文）
        remote_path = str(PurePosixPath(root_dir) / PurePosixPath(server_path.lstrip("/")))
        
        # Prepare SSL Context
        ssl_ctx = None
        if ftps_explicit or ftps_implicit:
            ssl_ctx = ssl.create_default_context()
            if not ssl_verify:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

        client = aioftp.Client()
        try:
            # Connect
            if ftps_implicit:
                await client.connect(host, port, ssl=ssl_ctx or True)
                await client.login(user, password)
            elif ftps_explicit:
                await client.connect(host, port)
                await client.auth_tls(ssl=ssl_ctx or True)
                await client.login(user, password)
            else:
                await client.connect(host, port)
                await client.login(user, password)

            if operation == "upload":
                if not local_path:
                    raise ValueError("缺少 local_path")
                if not os.path.isfile(local_path):
                    raise ValueError(f"本地文件不存在或不是文件: {local_path}")
                
                # 显式计算最终目标路径，避免 aioftp write_into 参数的歧义
                # 默认策略：假设它是文件路径
                is_dir_target = False
                
                # 策略1: 显式目录标识 (以 / 结尾)
                if server_path.strip().endswith("/") or server_path.strip() == "":
                    is_dir_target = True
                
                # 策略2: 如果不以 / 结尾，但看起来不像文件 (没有后缀)，且服务端可能存在该目录 -> 尝试探测
                # 反之，如果包含后缀 (如 .html, .jpg)，我们强烈假设它是文件，跳过目录探测 (除非上传失败)
                elif "." not in PurePosixPath(server_path).name:
                    try:
                        stat_res = await client.stat(remote_path)
                        if stat_res and "type" in stat_res and stat_res["type"] == "dir":
                            is_dir_target = True
                    except Exception:
                        pass
                
                # 策略3 (冗余): 如果用户明确指定了后缀，强制视为文件模式 (is_dir_target = False)
                if "." in PurePosixPath(server_path).name:
                     is_dir_target = False

                if is_dir_target:
                    # 如果目标是目录，追加文件名
                    local_name = os.path.basename(local_path)
                    final_remote_path = str(PurePosixPath(remote_path) / local_name)
                else:
                    # 如果目标是文件路径，直接使用
                    final_remote_path = remote_path

                # 强制使用 write_into=False，因为我们已经计算了完整路径
                # 这告诉 aioftp: "这就是我要上传到的完整路径，不要再把它当目录处理了"
                try:
                    await client.upload(local_path, final_remote_path, write_into=False)
                except aioftp.StatusCodeError as e:
                    # 容错重试：如果上传失败且提示 Is a directory (553 或类似)，
                    # 说明服务端确实有个同名目录，但我们之前的判断漏掉了。
                    # 此时必须将文件上传到该目录下，而不是覆盖目录。
                    if "directory" in str(e).lower() or "folder" in str(e).lower() or e.received_codes == ('553',):
                         local_name = os.path.basename(local_path)
                         retry_path = str(PurePosixPath(remote_path) / local_name)
                         # 防止死循环 (比如 target 就是 /a/b.jpg 且确实是目录? 极少见)
                         if retry_path != final_remote_path: 
                             await client.upload(local_path, retry_path, write_into=False)
                             final_remote_path = retry_path
                         else:
                             raise e
                    else:
                        raise e
                
                url = self._build_url(base_url, root_dir, final_remote_path)
                return {"ok": True, "operation": operation, "remote_path": final_remote_path, "url": url, "message": f"已上传到 {final_remote_path}" + (f" 可访问: {url}" if url else "")}

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
        finally:
            try:
                await client.quit()
            except Exception:
                pass


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
