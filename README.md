# astrbot_plugin_ftp_control

通过 LLM 工具执行 FTP 文件操作的 AstrBot 插件。

## 功能特性
- 注册一个 LLM 工具 `ftp_manage`，支持以下操作：
  - `upload`：上传本地文件到服务器路径
  - `download`：从服务器下载文件到本地路径
  - `delete`：删除服务器上的文件或目录（递归）
  - `rename`：重命名服务器上的文件或目录
  - `mkdir`：在服务器上创建目录
  - `list`：列出服务器路径下的文件/目录
- 所有服务器连接信息从插件配置读取，避免在工具参数中传递凭据。
- 异步实现，操作结果会：
  - 通过 `await event.send(...)` 发送给当前会话用户
  - 以结构化对象返回给 LLM，便于后续决策

## 环境要求
- AstrBot（3.4+）
- Python 3.10+
- 依赖：`aioftp`

## 安装部署
1. 将本项目放置到 AstrBot 的插件目录：
   - `AstrBot/data/plugins/astrbot_plugin_ftp_control`
2. 安装依赖（AstrBot 会在插件管理中读取 `requirements.txt` 并安装）：
   - `requirements.txt`
   - 依赖内容：`aioftp>=0.27.2`
3. 在 AstrBot WebUI 插件管理中启用本插件，点击“管理”，按需“重载插件”。

## 配置说明
插件会读取 `_conf_schema.json` 生成配置界面，并在实例化时注入 `config`：
- `server.ip`：FTP 服务器 IP
- `server.port`：FTP 端口（默认 `21`）
- `server.username`：用户名
- `server.password`：密码
- `ftp_root_dir`：FTP 根目录（远程），默认 `/`
- `base_access_url`：基础访问 URL（可选，用于拼接可访问链接）

> 提示：`base_access_url` 若不为空，插件会将 `ftp_root_dir` 下的相对路径与该 URL 拼接用于展示可访问链接（例如 CDN 或 Web 服务器暴露的静态资源路径）。

## LLM 工具接口
- 工具名：`ftp_manage`
- 工具参数：
  - `operation`（string）：`upload | download | delete | rename | mkdir | list`
  - `server_path`（string）：服务器上的路径（会拼接到 `ftp_root_dir` 下）
  - `local_path`（string）：本地文件路径（上传/下载时需要）
  - `new_name`（string）：新名字（用于 `rename`）
- 返回值（结构化）：
  - 成功示例（上传）：
    ```json
    {
      "ok": true,
      "operation": "upload",
      "remote_path": "/root/uploads/a.txt",
      "url": "https://example.com/uploads/a.txt",
      "message": "已上传到 /root/uploads/a.txt 可访问: https://example.com/uploads/a.txt"
    }
    ```
  - 失败示例：
    ```json
    {
      "ok": false,
      "error": "530 Login authentication failed",
      "operation": "upload",
      "server_path": "/uploads/a.txt"
    }
    ```

## 使用示例
- 上传：
  - `operation="upload"`, `server_path="/uploads/a.txt"`, `local_path="D:/files/a.txt"`
- 下载：
  - `operation="download"`, `server_path="/docs/readme.md"`, `local_path="D:/downloads/readme.md"`
- 删除：
  - `operation="delete"`, `server_path="/old/unused.bin"`
- 重命名：
  - `operation="rename"`, `server_path="/images/pic.jpg"`, `new_name="pic_v2.jpg"`
- 建目录：
  - `operation="mkdir"`, `server_path="/new-folder"`
- 列目录：
  - `operation="list"`, `server_path="/images"`

> 在默认工作流中，LLM 会选择并调用该工具，插件会发送消息给用户并返回结构化结果给 LLM。

## 常见问题
- `530 Login authentication failed`：检查用户名/密码是否正确，是否需要使用 TLS（FTPS）登录；确认端口号与安全模式匹配；可先用通用 FTP 客户端验证。
- Windows 本地路径：建议使用绝对路径（例如 `D:/downloads/readme.md`）。
- `base_access_url` 无法拼接：确保该 URL 的根与 `ftp_root_dir` 对应，且远程路径在根目录之下。

## 目录结构
```
astrbot_plugin_ftp_control/
├─ main.py               # 插件主文件，注册 llm_tool 并实现 FTP 逻辑
├─ _conf_schema.json     # 插件配置 Schema（自动生成配置界面）
├─ metadata.yaml         # 插件元信息（市场展示）
└─ requirements.txt      # 依赖声明（aioftp）
```

## 开发说明
- 参考 AstrBot 开发文档（本项目含 `astrbot开发.txt`）。
- 代码中使用 `await event.send(...)` 发送用户消息，并返回结构化结果给 LLM。
- 异步 FTP 基于 `aioftp`：`upload/download/remove/rename/make_directory/list`。

## 版本
- `1.0.0`：初始发布

## 作者
- 作者：`Xican`